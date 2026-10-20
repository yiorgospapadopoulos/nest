import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from nestd.providers.base import AccountInfo, EngineWindow, ModelOption, UsageInfo, window_label
from nestd.providers.codex_engine import (
    MAX_PAGES,
    CodexFetchError,
    CodexLogin,
    codex_login,
    codex_models,
    fetch_codex,
    fetch_codex_usage,
)
from nestd.providers.codex_limits import codex_usage
from nestd.providers.codex_process import CodexLaunch
from nestd.providers.codex_rpc import JsonObject
from tests.codex_support import MODELS, SIGNED_OUT, FakeAppServer

LAUNCH = CodexLaunch(("codex", "app-server"), {})


def test_models_come_in_codexs_order_after_its_default() -> None:
    models = codex_models(MODELS)

    assert [m.value for m in models] == ["default", "gpt-6.1-sol", "gpt-5.5"]
    assert models[0] == ModelOption(
        value="default",
        display_name="Default (GPT-6.1 Sol)",
        description="Codex's default model",
        effort_levels=["low", "high"],
        supports_effort=True,
        supports_auto_mode=True,
        resolved_model="gpt-6.1-sol",
    )
    assert models[2].effort_levels == []
    assert not models[2].supports_effort


def test_a_list_without_a_default_or_with_odd_entries_keeps_what_it_can() -> None:
    page: JsonObject = {"data": [{"id": "only-id"}, {"model": ""}, "junk"]}

    assert [(m.value, m.display_name) for m in codex_models(page)] == [("only-id", "only-id")]
    assert codex_models({}) == []


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (
            {"account": {"type": "chatgpt", "email": "me@x.dev", "planType": "pro"}},
            CodexLogin(True, AccountInfo(email="me@x.dev", plan="ChatGPT Pro")),
        ),
        (
            {"account": {"type": "chatgpt", "email": None, "planType": "prolite"}},
            CodexLogin(True, AccountInfo(plan="ChatGPT Prolite")),
        ),
        (
            {"account": {"type": "chatgpt", "planType": None}},
            CodexLogin(True, AccountInfo(plan="ChatGPT")),
        ),
        ({"account": {"type": "apiKey"}}, CodexLogin(True, AccountInfo(plan="OpenAI API key"))),
        (
            {"account": {"type": "amazonBedrock"}},
            CodexLogin(True, AccountInfo(plan="Amazon Bedrock")),
        ),
        (SIGNED_OUT, CodexLogin(False, AccountInfo())),
        ({"account": None, "requiresOpenaiAuth": False}, CodexLogin(True, AccountInfo())),
    ],
)
def test_the_login_says_whether_codex_can_run(
    response: dict[str, object], expected: CodexLogin
) -> None:
    assert codex_login(response) == expected  # type: ignore[arg-type]


async def test_fetch_asks_a_short_lived_server_and_closes_it() -> None:
    server = FakeAppServer()

    details = await fetch_codex(server, LAUNCH)

    assert [m.value for m in details.models] == ["default", "gpt-6.1-sol", "gpt-5.5"]
    assert details.login.signed_in
    assert [m["method"] for m in server.sent] == [
        "initialize",
        "initialized",
        "model/list",
        "account/read",
    ]
    assert server.requests("initialize")[0]["capabilities"] == {
        "experimentalApi": False,
        "requestAttestation": False,
    }
    assert server.transport.closed
    assert server.launches == [LAUNCH]


async def test_fetch_follows_the_model_list_pages() -> None:
    server = FakeAppServer()
    first: JsonObject = {**MODELS, "nextCursor": "page-2"}
    last: JsonObject = {"data": [], "nextCursor": None}
    pages = iter([first, last])
    server.answers["model/list"] = lambda _params: next(pages)

    await fetch_codex(server, LAUNCH)

    assert [p["cursor"] for p in server.requests("model/list")] == [None, "page-2"]


async def test_fetch_failures_keep_only_their_kind() -> None:
    server = FakeAppServer()
    server.errors["account/read"] = (-32600, "token /Users/me/.codex/auth.json invalid")

    with pytest.raises(CodexFetchError, match=r"^CodexRpcError$"):
        await fetch_codex(server, LAUNCH)


async def test_a_fetch_that_hangs_times_out() -> None:
    server = FakeAppServer()
    server.silent.add("model/list")

    with pytest.raises(CodexFetchError, match="timed out"):
        await fetch_codex(server, LAUNCH, timedelta(milliseconds=50))
    await asyncio.sleep(0)


async def test_a_model_list_whose_pages_never_end_is_read_up_to_a_limit() -> None:
    server = FakeAppServer()
    server.answers["model/list"] = {"data": [], "nextCursor": "again"}

    details = await fetch_codex(server, LAUNCH)

    assert details.models == []
    assert len(server.requests("model/list")) == MAX_PAGES


async def test_what_codex_sends_while_asked_is_ignored_or_refused() -> None:
    server = FakeAppServer()
    asked: list[object] = []

    def answer_and_ask(_params: JsonObject) -> JsonObject:
        server.notify("remoteControl/status/changed", {"status": "disabled"})
        asked.append(asyncio.ensure_future(server.request("item/tool/call", {})))
        return {"userAgent": "nest"}

    server.answers["initialize"] = answer_and_ask

    await fetch_codex(server, LAUNCH)

    reply = await asked[0]  # type: ignore[misc]
    assert reply["result"] == {}


async def test_usage_is_read_from_a_short_lived_server_without_a_turn() -> None:
    server = FakeAppServer()

    usage = await fetch_codex_usage(server, LAUNCH)

    assert usage == UsageInfo(
        five_hour=None,
        seven_day=None,
        provider="codex",
        windows=[
            EngineWindow(
                utilization=0.3, resets_at=datetime(2026, 1, 1, 16, tzinfo=UTC), minutes=300
            ),
            EngineWindow(utilization=0.815, resets_at=None, minutes=10080),
        ],
    )
    assert [m["method"] for m in server.sent] == [
        "initialize",
        "initialized",
        "account/rateLimits/read",
    ]
    assert server.requests("account/rateLimits/read") == [{"excludeResetCreditDetails": True}]
    assert server.transport.closed


async def test_usage_of_a_signed_out_codex_fails_with_its_kind_only() -> None:
    server = FakeAppServer()
    server.errors["account/rateLimits/read"] = (-32600, "codex account authentication required")

    with pytest.raises(CodexFetchError, match=r"^CodexRpcError$"):
        await fetch_codex_usage(server, LAUNCH)


@pytest.mark.parametrize(
    ("snapshot", "windows"),
    [
        # The free plan, as recorded live (B91): one 30-day window, no secondary.
        (
            {
                "limitId": "codex",
                "primary": {"usedPercent": 4, "windowDurationMins": 43200, "resetsAt": None},
                "secondary": None,
                "planType": "free",
            },
            [(43200, 0.04, "30 day")],
        ),
        # A weekly window alone, in the primary place.
        ({"primary": {"usedPercent": 12, "windowDurationMins": 10080}}, [(10080, 0.12, "Weekly")]),
        # Shortest first, whatever their places.
        (
            {
                "primary": {"usedPercent": 50, "windowDurationMins": 43200},
                "secondary": {"usedPercent": 5, "windowDurationMins": 60},
            },
            [(60, 0.05, "1 hour"), (43200, 0.5, "30 day")],
        ),
        # Two windows of one length: the first is kept.
        (
            {
                "primary": {"usedPercent": 10, "windowDurationMins": 300},
                "secondary": {"usedPercent": 20, "windowDurationMins": 300},
            },
            [(300, 0.1, "5 hour")],
        ),
        # A window without a length comes last.
        (
            {
                "primary": {"usedPercent": -3, "windowDurationMins": None},
                "secondary": {"usedPercent": 1, "windowDurationMins": 2880},
            },
            [(2880, 0.01, "2 day"), (None, 0.0, "Usage")],
        ),
    ],
)
def test_codex_windows_keep_their_lengths_and_are_labelled_by_them(
    snapshot: JsonObject, windows: list[tuple[int | None, float, str]]
) -> None:
    usage = codex_usage(snapshot)

    assert usage is not None
    assert usage.provider == "codex"
    assert usage.five_hour is None
    assert usage.seven_day is None
    assert [(w.minutes, w.utilization, w.label) for w in usage.windows] == windows


@pytest.mark.parametrize(
    ("minutes", "label"),
    [
        (300, "5 hour"),
        (10080, "Weekly"),
        (43200, "30 day"),
        (1440, "1 day"),
        (120, "2 hour"),
        (90, "90 minute"),
        (None, "Usage"),
    ],
)
def test_a_window_is_labelled_by_its_length(minutes: int | None, label: str) -> None:
    assert window_label(minutes) == label


def test_a_snapshot_without_windows_is_no_usage() -> None:
    assert codex_usage({}) is None
    assert codex_usage({"primary": {"usedPercent": None}, "secondary": "junk"}) is None
