"""An artifact page asks Claude (B88 stage 4): one small Agent SDK call like the usage probe,
within a daily budget per artifact, one at a time per artifact and two daemon-wide, its
tokens counted apart, and every open reader told when it starts and finishes.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from nestd.artifacts.ask import ASK_PREAMBLE, AskBusyError, AskFailedError, PageAsks, ask_options
from nestd.artifacts.models import Origin
from nestd.config.models import ArtifactSettings
from nestd.events import types
from nestd.local.run import LocalRun, claude_env
from nestd.providers.base import RunAccount
from tests.api_client import Api, running_api
from tests.fake_probe import rate_limit, result
from tests.fakes import FakeClock, FakeSecretStore

ORIGIN = Origin(session_id="s1", repo="web", chat_title="Fix the bug", pixie_id=None)


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.fixture
def events(api: Api, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    sent: list[dict[str, Any]] = []
    publish = api.ctx.bus.publish_ephemeral

    async def record(event_type: str, payload: dict[str, Any], session_id: str | None = None):  # noqa: ANN202
        if event_type == types.ARTIFACT_ASK:
            sent.append(dict(payload))
        return await publish(event_type, payload, session_id)

    monkeypatch.setattr(api.ctx.bus, "publish_ephemeral", record)
    return sent


def reply(text: str = "A bright day.", output_tokens: int = 20) -> list[Any]:
    return [
        rate_limit(0.3),
        AssistantMessage(content=[TextBlock(text)], model="claude-haiku"),
        result(500, output_tokens),
    ]


def limit(api: Api, **changes: object) -> None:
    api.ctx.settings = api.ctx.settings.model_copy(
        update={"artifacts": api.ctx.settings.artifacts.model_copy(update=changes)}
    )


async def page(api: Api) -> str:
    return (await api.ctx.artifacts.create(ORIGIN, "html", "Ask", "<button>Ask</button>")).id


async def ask(api: Api, artifact_id: str, **body: object) -> Any:  # noqa: ANN401
    return await api.http.post(
        f"/api/artifacts/{artifact_id}/ask", json={"prompt": "A haiku about today", **body}
    )


def test_the_call_is_as_small_as_the_usage_probe(tmp_path: Path) -> None:
    settings = ArtifactSettings(ask_model="sonnet", ask_max_output_tokens=300)

    options = ask_options(tmp_path, settings, "Answer in French.")
    bare = ask_options(tmp_path, ArtifactSettings(), None)

    assert options.cwd == tmp_path
    assert options.model == "sonnet"
    assert options.system_prompt == f"{ASK_PREAMBLE}\n\nAnswer in French."
    assert options.tools == []
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.mcp_servers == {}
    assert options.thinking == {"type": "disabled"}
    assert options.max_turns == 1
    assert options.extra_args == {"no-session-persistence": None}
    assert options.env == {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "300"}
    assert (bare.model, bare.system_prompt) == ("haiku", ASK_PREAMBLE)
    assert bare.env == {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": "1000"}
    assert ASK_PREAMBLE == (
        "You answer a request from an interactive page the user opened in Nest. Reply with"
        " plain text only, no tools, briefly."
    )


async def test_a_page_asks_and_gets_plain_text(api: Api, events: list[dict[str, Any]]) -> None:
    artifact_id = await page(api)
    api.probes.replies.append(reply())

    response = await ask(api, artifact_id, system="Be brief.")

    [client] = api.probes.clients
    assert response.status_code == 200
    assert response.json() == {"text": "A bright day.", "remaining": 19, "limit": 20}
    assert client.prompts == ["A haiku about today"]
    assert client.options.cwd == api.ctx.paths.ask_dir
    assert client.options.system_prompt == f"{ASK_PREAMBLE}\n\nBe brief."
    assert client.disconnects == 1
    assert events == [
        {"artifact_id": artifact_id, "state": "started", "remaining": 19, "limit": 20},
        {"artifact_id": artifact_id, "state": "finished", "remaining": 19, "limit": 20},
    ]
    rows = await api.ctx.db.fetch_all(
        "SELECT artifact_id, input_tokens, output_tokens, ok FROM artifact_asks"
    )
    assert [tuple(row) for row in rows] == [(artifact_id, 500, 20, 1)]
    day = await api.ctx.usage.period("day", api.ctx.clock.now().date())
    assert day.asks.model_dump() == {"count": 1, "tokens": 520}
    assert day.tokens.total == 0


async def test_the_answer_falls_back_to_the_result_text(api: Api) -> None:
    artifact_id = await page(api)
    done = result()
    done.result = "  From the result.  "
    api.probes.replies.append([done])

    response = await ask(api, artifact_id)

    assert response.json()["text"] == "From the result."


@pytest.mark.parametrize(
    ("script", "reason"),
    [
        (RuntimeError("engine crashed: secret path"), "RuntimeError"),
        ([], "the engine ended before the reply"),
        ("error", "the engine reported an error"),
        ("connect", "OSError"),
    ],
)
async def test_a_failed_call_counts_and_says_why_without_details(
    api: Api, events: list[dict[str, Any]], script: object, reason: str
) -> None:
    artifact_id = await page(api)
    if script == "error":
        failed = result()
        failed.is_error = True
        api.probes.replies.append([failed])
    elif script == "connect":
        api.probes.connect_error = OSError("no login")
    else:
        api.probes.replies.append(script)  # type: ignore[arg-type]

    response = await ask(api, artifact_id)

    assert response.status_code == 502
    assert response.json() == {"detail": f"Claude did not answer ({reason})"}
    assert [e["state"] for e in events] == ["started", "finished"]
    rows = await api.ctx.db.fetch_all("SELECT input_tokens, ok FROM artifact_asks")
    assert [tuple(row) for row in rows] == [(None, 0)]
    assert api.probes.clients[0].disconnects == 1
    assert (await api.ctx.usage.period("day", api.ctx.clock.now().date())).asks.count == 0


async def test_the_daily_budget_counts_every_ask_and_resets_at_local_midnight(
    api: Api, clock: FakeClock
) -> None:
    limit(api, ask_daily_limit=2)
    artifact_id = await page(api)
    other = await page(api)
    api.probes.replies.extend([reply(), RuntimeError("x"), reply(), reply()])

    first = await ask(api, artifact_id)
    failed = await ask(api, artifact_id)
    over = await ask(api, artifact_id)
    elsewhere = await ask(api, other)
    clock.current = datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)
    still_over = await ask(api, artifact_id)
    clock.current = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    next_day = await ask(api, artifact_id)

    assert first.json()["remaining"] == 1
    assert failed.status_code == 502
    assert over.status_code == 429
    assert over.json() == {
        "detail": (
            "This page has used its 2 asks for today; they reset at 2026-01-02T00:00:00+00:00"
        ),
        "resets_at": "2026-01-02T00:00:00+00:00",
    }
    assert elsewhere.json()["remaining"] == 1
    assert still_over.status_code == 429
    assert next_day.json() == {"text": "A bright day.", "remaining": 1, "limit": 2}
    assert api.probes.prompts == 4


async def test_asking_can_be_turned_off(api: Api) -> None:
    artifact_id = await page(api)
    limit(api, ask=False)

    response = await ask(api, artifact_id)

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Asking Claude from pages is turned off in Nest's settings"
    }
    assert api.probes.clients == []


@pytest.mark.parametrize(
    ("body", "status"),
    [
        ({"prompt": ""}, 422),
        ({"prompt": "p" * 8001}, 422),
        ({"prompt": "p" * 8000, "system": "s" * 4001}, 422),
        ({"system": "s"}, 422),
    ],
)
async def test_bad_asks_are_refused(api: Api, body: dict[str, object], status: int) -> None:
    artifact_id = await page(api)

    response = await api.http.post(f"/api/artifacts/{artifact_id}/ask", json=body)

    assert response.status_code == status
    assert api.probes.clients == []


async def test_an_unknown_artifact_or_device_is_refused(api: Api) -> None:
    unknown = await ask(api, "nope")
    no_device = await api.http.post(
        "/api/artifacts/nope/ask", json={"prompt": "x"}, headers={"Authorization": "Bearer wrong"}
    )

    assert (unknown.status_code, no_device.status_code) == (404, 401)


async def test_deleting_the_artifact_forgets_its_asks_but_not_their_tokens(api: Api) -> None:
    artifact_id = await page(api)
    api.probes.replies.append(reply())
    await ask(api, artifact_id)

    await api.ctx.artifacts.delete(artifact_id)

    assert await api.ctx.db.fetch_all("SELECT * FROM artifact_asks") == []
    assert (await api.ctx.usage.period("day", api.ctx.clock.now().date())).asks.count == 1


def asks(api: Api, **overrides: Any) -> PageAsks:  # noqa: ANN401
    options: dict[str, Any] = {
        "db": api.ctx.db,
        "bus": api.ctx.bus,
        "clock": api.ctx.clock,
        "usage": api.ctx.usage,
        "factory": api.probes,
        "cwd": api.ctx.paths.ask_dir,
        "settings": lambda: api.ctx.settings.artifacts,
        **overrides,
    }
    return PageAsks(**options)


async def test_a_call_that_takes_too_long_is_given_up(api: Api) -> None:
    artifact_id = await page(api)
    api.probes.hang = True

    with pytest.raises(AskFailedError, match=r"^Claude did not answer \(timed out\)$"):
        await asks(api, timeout=timedelta(milliseconds=10)).ask(artifact_id, "x", None)

    assert api.probes.clients[0].disconnects == 1


async def test_one_ask_at_a_time_per_artifact_and_two_daemon_wide(api: Api) -> None:
    first, second, third = await page(api), await page(api), await page(api)
    api.probes.hang = True
    service = asks(api, wait=timedelta(milliseconds=50))
    running = [asyncio.create_task(service.ask(a, "x", None)) for a in (first, second)]
    await asyncio.sleep(0.01)

    try:
        with pytest.raises(AskBusyError, match="already asking Claude"):
            await service.ask(first, "y", None)
        with pytest.raises(AskBusyError, match="busy with other pages' asks"):
            await service.ask(third, "z", None)
        # The waiting ask gave up its place: the artifact may ask again later.
        with pytest.raises(AskBusyError, match="busy with other pages' asks"):
            await service.ask(third, "z", None)
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    api.probes.hang = False
    api.probes.replies.append(reply("Freed."))
    assert (await service.ask(first, "again", None)).text == "Freed."


async def test_the_budget_counts_by_the_systems_local_day_without_a_zone(api: Api) -> None:
    artifact_id = await page(api)
    status = await asks(api, zone=None).status(artifact_id)

    midnight = datetime.combine(api.ctx.clock.now().astimezone().date(), datetime.min.time())
    assert (status.used, status.limit) == (0, 20)
    assert status.resets_at == (midnight + timedelta(days=1)).astimezone()


async def test_a_reader_reads_todays_asks_when_it_opens(api: Api) -> None:
    limit(api, ask_daily_limit=3)
    artifact_id = await page(api)
    url = f"/api/artifacts/{artifact_id}/ask"
    before = (await api.http.get(url)).json()
    api.probes.replies.extend([reply(), reply(), reply()])
    for _ in range(3):
        await ask(api, artifact_id)
    limit(api, ask_daily_limit=2, ask=False)

    after = (await api.http.get(url)).json()
    unknown = await api.http.get("/api/artifacts/nope/ask")

    assert before == {
        "used": 0,
        "limit": 3,
        "remaining": 3,
        "resets_at": "2026-01-02T00:00:00Z",
        "enabled": True,
    }
    # A lower limit set later never shows a negative count.
    assert (after["used"], after["limit"], after["remaining"], after["enabled"]) == (3, 2, 0, False)
    assert unknown.status_code == 404


async def test_an_ask_goes_to_a_local_model_when_claude_cannot_take_it(api: Api) -> None:
    """B106: without a Claude login, the first local model answers; no account is used."""
    artifact_id = await page(api)
    run = LocalRun(
        model_id="lm_1",
        model="qwen3-coder",
        context=None,
        vision=False,
        thinking=False,
        base_url_for_claude="http://127.0.0.1:1234",
        key_for_claude="nest-local",
        base_url_for_codex="http://127.0.0.1:1234/v1",
        key_for_codex="nest-local",
    )

    async def local() -> LocalRun:
        return run

    async def account() -> RunAccount:
        raise AssertionError("a local ask runs on no account")

    api.probes.replies.append(reply("Local."))

    answer = await asks(api, local=local, account=account).ask(artifact_id, "x", None)

    assert answer.text == "Local."
    options = api.probes.clients[-1].options
    assert options.model == "qwen3-coder"
    assert options.env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:1234"
    assert options.settings is not None
    assert json.loads(options.settings)["env"] == claude_env(run)
