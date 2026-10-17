import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nestd.gitops.runner import CommandError
from nestd.local_apps.apps import LIVE_WARNING
from nestd.providers.base import McpServer, TokenUsage, UsageInfo, UsageWindow
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import (
    FakeRun,
    background,
    hang,
    limits,
    loaded,
    reply,
    subagent_reply,
)
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/connectors"),
        ("GET", "/api/usage/period?unit=month&date=2026-01-01"),
        ("GET", "/api/usage/limits"),
        ("POST", "/api/sessions/x/open-in-claude-code"),
        ("POST", "/api/repos/repo/open"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_connectors_settle_after_the_first_turn(api: Api) -> None:
    pending = [McpServer("plugin:engineering:github", "pending")]
    api.provider.statuses = [
        McpServer("plugin:engineering:github", "needs-auth"),
        McpServer("claude.ai Gmail", "connected"),
    ]
    api.provider.script(loaded(pending, reply("ok")))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    async def settled() -> bool:
        return len((await api.http.get("/api/connectors")).json()) == 2

    await until(settled)

    connectors = (await api.http.get("/api/connectors")).json()

    assert [(c["display_name"], c["group"], c["status"], c["manage_hint"]) for c in connectors] == [
        ("Gmail", "claude.ai", "connected", "claude.ai"),
        ("github", "plugin", "needs-auth", "claude_code"),
    ]
    assert connectors[0]["name"] == "claude.ai Gmail"
    assert connectors[0]["source"] == session_id


async def test_token_usage_of_chats_and_subagents_by_period(api: Api, clock: FakeClock) -> None:
    api.provider.script(
        subagent_reply(
            "msg_1",
            TokenUsage(input_tokens=2, output_tokens=4),
            then=subagent_reply(
                "msg_1",
                TokenUsage(input_tokens=2, output_tokens=7),
                then=reply("one", tokens=TokenUsage(input_tokens=10, output_tokens=5)),
            ),
        ),
        reply("two", tokens=TokenUsage(cache_read_input_tokens=100)),
    )
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "more"})
    await reach(api, session_id, "idle", results=2)

    month = (
        await api.http.get("/api/usage/period", params={"unit": "month", "date": "2026-01-20"})
    ).json()
    day = (
        await api.http.get("/api/usage/period", params={"unit": "day", "date": "2026-01-01"})
    ).json()
    empty = (
        await api.http.get("/api/usage/period", params={"unit": "week", "date": "2026-02-02"})
    ).json()

    assert (month["unit"], month["start"], month["end"], month["current"]) == (
        "month",
        "2026-01-01",
        "2026-01-31",
        True,
    )
    assert month["sessions"] == 1
    assert month["tokens"] == {
        "input_tokens": 12,
        "output_tokens": 12,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 100,
        "total": 124,
    }
    assert month["subagents"]["total"] == 9
    assert month["bars"][0] == {"start": "2026-01-01T00:00:00Z", "tokens": 124, "sessions": 1}
    assert len(month["bars"]) == 31
    assert month["projects"] == [{"name": "repo", "tokens": 124, "pixies": False}]
    assert month["probes"] == {"count": 0, "tokens": 0}
    assert (len(day["bars"]), day["bars"][12]["tokens"]) == (24, 124)
    assert (empty["start"], empty["end"], empty["current"]) == ("2026-02-02", "2026-02-08", False)
    assert (empty["sessions"], empty["tokens"]["total"], empty["projects"]) == (0, 0, [])


@pytest.mark.parametrize(
    "params",
    [
        {"unit": "hour", "date": "2026-01-01"},
        {"unit": "month", "date": "2026-13-01"},
        {"unit": "month", "date": "yesterday"},
        {"unit": "month", "date": "1999-12-31"},
        {"unit": "year", "date": "2101-01-01"},
        {"unit": "month"},
        {"date": "2026-01-01"},
    ],
)
async def test_period_needs_a_known_unit_and_a_valid_date(api: Api, params: dict[str, str]) -> None:
    assert (await api.http.get("/api/usage/period", params=params)).status_code == 422


async def test_the_month_endpoint_is_gone(api: Api) -> None:
    response = await api.http.get("/api/usage/month", params={"year": 2026, "month": 1})

    assert response.status_code == 404


async def test_usage_limits_survive_a_restart(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    resets = datetime(2026, 1, 1, 17, tzinfo=UTC)
    info = UsageInfo(five_hour=UsageWindow(utilization=0.25, resets_at=resets), seven_day=None)
    async with running_api(tmp_path, clock, secrets) as first:
        await first.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        first.provider.script(limits(info, reply("ok")))
        session_id = str((await create(first))["id"])
        await reach(first, session_id, "idle")

    async with running_api(tmp_path, clock, secrets) as second:
        response = await second.http.get("/api/usage/limits")

    assert response.json() == {
        "five_hour": {
            "utilization": 0.25,
            "resets_at": "2026-01-01T17:00:00Z",
            "updated_at": "2026-01-01T12:00:00Z",
        },
        "seven_day": None,
    }


async def test_open_in_claude_code(api: Api) -> None:
    """PL-15: Nest's idle run closes first, so a later message from Nest resumes the
    conversation with what was done in Terminal instead of forking it.
    """
    api.provider.script(reply("ok"))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    (run,) = api.provider.runs

    opened = await api.http.post(f"/api/sessions/{session_id}/open-in-claude-code")
    unknown = await api.http.post("/api/sessions/nope/open-in-claude-code")

    assert opened.status_code == 200
    assert run.closed
    assert not api.ctx.sessions.has_run(session_id)
    assert opened.json()["warning"] is None
    launcher = Path(opened.json()["launcher"])
    assert launcher == api.ctx.paths.launchers_dir / f"{session_id}.command"
    assert api.opener.calls[-1][0] == ("open", str(launcher))
    assert unknown.status_code == 404


async def test_open_in_claude_code_keeps_a_run_with_background_work(api: Api) -> None:
    """Closing would stop the agent's background tasks; both run, with a warning."""
    api.provider.script(background(1, reply("started a background agent")))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    (run,) = api.provider.runs

    opened = await api.http.post(f"/api/sessions/{session_id}/open-in-claude-code")

    assert opened.json()["warning"] == LIVE_WARNING
    assert not run.closed


async def test_open_in_claude_code_keeps_a_run_whose_turn_is_in_progress(api: Api) -> None:
    release = asyncio.Event()

    async def long_turn(run: FakeRun) -> None:
        await run.sink.provider_session_id("sdk-1")
        await release.wait()
        await reply("done")(run)

    api.provider.script(long_turn)
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "running")
    await until(lambda: bool(api.provider.runs) and bool(api.provider.runs[0].inputs))
    await until(_has_provider_session(api, session_id))

    opened = await api.http.post(f"/api/sessions/{session_id}/open-in-claude-code")
    release.set()
    await reach(api, session_id, "idle")

    assert opened.json()["warning"] == LIVE_WARNING
    assert not api.provider.runs[0].closed


def _has_provider_session(api: Api, session_id: str) -> Callable[[], Awaitable[bool]]:
    async def stored() -> bool:
        return (await api.ctx.sessions.get(session_id)).provider_session_id is not None

    return stored


async def test_open_in_claude_code_before_the_agent_started(api: Api) -> None:
    api.provider.script(hang())
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "running")

    response = await api.http.post(f"/api/sessions/{session_id}/open-in-claude-code")

    assert response.status_code == 409
    assert "no Claude Code conversation" in response.json()["detail"]
    assert api.opener.calls == []


async def test_open_a_repo_in_local_apps(api: Api) -> None:
    path = str(api.ctx.repos.get("repo").path)

    opened = await api.http.post("/api/repos/repo/open", json={"app": "vscode"})
    api.opener.failure = CommandError(
        ["open"], 1, "Unable to find application named 'Visual Studio Code'\n"
    )
    missing = await api.http.post("/api/repos/repo/open", json={"app": "vscode"})
    other_app = await api.http.post("/api/repos/repo/open", json={"app": "xcode"})
    unknown_repo = await api.http.post("/api/repos/nope/open", json={"app": "finder"})

    assert opened.status_code == 204
    assert api.opener.calls[0][0] == ("open", "-a", "Visual Studio Code", path)
    assert missing.status_code == 424
    assert missing.json() == {"detail": "Visual Studio Code is not installed on this Mac"}
    assert other_app.status_code == 422
    assert unknown_repo.status_code == 404
