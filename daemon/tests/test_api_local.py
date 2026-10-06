from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest

from harness.gitops.runner import CommandError
from harness.local_apps.apps import LIVE_WARNING
from harness.providers.base import McpServer, TokenUsage, UsageInfo, UsageWindow
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import hang, limits, loaded, reply
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
        ("GET", "/api/usage/month?year=2026&month=1"),
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


async def test_token_usage_per_turn_and_month(api: Api, clock: FakeClock) -> None:
    api.provider.script(
        reply("one", tokens=TokenUsage(input_tokens=10, output_tokens=5)),
        reply("two", tokens=TokenUsage(cache_read_input_tokens=100)),
    )
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "more"})
    await reach(api, session_id, "idle", results=2)

    month = (await api.http.get("/api/usage/month", params={"year": 2026, "month": 1})).json()
    empty = (await api.http.get("/api/usage/month", params={"year": 2026, "month": 2})).json()

    assert month["sessions"] == 1
    assert month["tokens"] == {
        "input_tokens": 10,
        "output_tokens": 5,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 100,
        "total": 115,
    }
    assert month["days"][0] == {
        "date": clock.now().date().isoformat(),
        "tokens": 115,
        "sessions": 1,
    }
    assert len(month["days"]) == 31
    assert empty["sessions"] == 0


@pytest.mark.parametrize(
    "params",
    [{"year": 2026, "month": 13}, {"year": 2026, "month": 0}, {"year": 1999, "month": 1}, {}],
)
async def test_month_needs_a_valid_year_and_month(api: Api, params: dict[str, int]) -> None:
    assert (await api.http.get("/api/usage/month", params=params)).status_code == 422


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
    api.provider.script(reply("ok"))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    live = await api.http.post(f"/api/sessions/{session_id}/open-in-claude-code")
    await api.http.patch(f"/api/sessions/{session_id}", json={"archived": True})
    released = await api.http.post(f"/api/sessions/{session_id}/open-in-claude-code")
    unknown = await api.http.post("/api/sessions/nope/open-in-claude-code")

    assert live.status_code == 200
    assert live.json()["warning"] == LIVE_WARNING
    assert released.json()["warning"] is None
    launcher = Path(released.json()["launcher"])
    assert launcher == api.ctx.paths.launchers_dir / f"{session_id}.command"
    assert api.opener.calls[-1][0] == ("open", str(launcher))
    assert unknown.status_code == 404


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
