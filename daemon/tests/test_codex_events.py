from datetime import UTC, datetime

from nestd.providers.base import (
    ContextUsage,
    EngineWindow,
    HookOutput,
    LimitHit,
    McpServer,
    ResultInfo,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
    ToolResultBlock,
    ToolUseBlock,
    UsageInfo,
)
from nestd.providers.codex_events import COMPACTED, CodexStream
from nestd.providers.codex_rpc import JsonObject
from tests.codex_support import item, note, turn_completed
from tests.recording_sink import RecordingSink


def stream() -> tuple[CodexStream, RecordingSink]:
    sink = RecordingSink()
    codex = CodexStream(sink)
    codex.thread_id = "thread-1"
    return codex, sink


async def feed(codex: CodexStream, *messages: JsonObject) -> None:
    for message in messages:
        params = message["params"]
        assert isinstance(params, dict)
        await codex.handle(str(message["method"]), params)


def usage(total: JsonObject, last: JsonObject, window: int | None = 200_000) -> JsonObject:
    return note(
        "thread/tokenUsage/updated",
        threadId="thread-1",
        turnId="turn-1",
        tokenUsage={"total": total, "last": last, "modelContextWindow": window},
    )


def started() -> JsonObject:
    return note("turn/started", threadId="thread-1", turn={"id": "turn-1"})


async def test_a_turn_streams_text_and_ends_with_its_result() -> None:
    codex, sink = stream()

    await feed(
        codex,
        started(),
        note("item/agentMessage/delta", threadId="thread-1", delta="Hel"),
        note("item/agentMessage/delta", threadId="thread-1", delta=""),
        item("completed", {"type": "agentMessage", "id": "a1", "text": "Hello"}),
        item("completed", {"type": "agentMessage", "id": "a2", "text": ""}),
        turn_completed(),
    )

    assert sink.calls == [
        ("text_delta", "Hel"),
        ("message", ([TextBlock(text="Hello")], None)),
        (
            "result",
            ResultInfo(is_error=False, subtype="success", duration_ms=1200, num_turns=1, errors=[]),
        ),
    ]
    assert codex.turn_id is None


async def test_reasoning_is_thinking_with_its_summary_and_duration() -> None:
    codex, sink = stream()

    await feed(
        codex,
        item("started", {"type": "reasoning", "id": "r1"}, at_ms=1000),
        note("item/reasoning/summaryTextDelta", threadId="thread-1", delta="Looking"),
        note("item/reasoning/summaryTextDelta", threadId="thread-1", delta=""),
        item(
            "completed",
            {"type": "reasoning", "id": "r1", "summary": ["Looking", "", "Found it"]},
            at_ms=3500,
        ),
    )

    assert sink.calls == [
        ("thinking", True),
        ("thinking_delta", ("Looking", None)),
        ("message", ([ThinkingBlock(text="Looking\n\nFound it", duration_ms=2500)], None)),
        ("thinking", False),
    ]


async def test_reasoning_with_nothing_to_show_is_no_thinking_block() -> None:
    """As Codex sends it on a low effort: an empty summary and no content."""
    codex, sink = stream()
    empty: JsonObject = {"type": "reasoning", "id": "rs_1", "summary": [], "content": []}

    await feed(
        codex,
        item("started", empty, at_ms=1000),
        item("completed", empty, at_ms=1000),
        item("completed", {"type": "reasoning", "id": "rs_2", "summary": [""]}),
    )

    assert sink.calls == [("thinking", True), ("thinking", False), ("thinking", False)]


async def test_reasoning_content_shows_when_there_is_no_summary() -> None:
    codex, sink = stream()

    await feed(
        codex,
        item(
            "completed",
            {"type": "reasoning", "id": "rs_1", "summary": [], "content": ["Weighing", "it"]},
        ),
    )

    assert sink.calls == [
        ("message", ([ThinkingBlock(text="Weighing\n\nit", duration_ms=None)], None)),
        ("thinking", False),
    ]


async def test_mcp_calls_in_progress_are_found_by_server_and_turn() -> None:
    codex, sink = stream()
    first: JsonObject = {"type": "mcpToolCall", "id": "m1", "server": "node_repl", "tool": "js"}
    second: JsonObject = {**first, "id": "m2", "tool": "js_reset"}
    other: JsonObject = {**first, "id": "m3", "server": "github", "tool": "list_issues"}

    await feed(codex, item("started", first), item("started", second), item("started", other))

    # The most recent call of the server in the turn is the one Codex asks about.
    assert codex.mcp_call("node_repl", "turn-1") == second
    assert codex.mcp_call("github", "turn-1") == other
    assert codex.mcp_call("node_repl", "turn-2") is None
    await feed(codex, item("completed", {**second, "status": "completed"}))
    assert codex.mcp_call("node_repl", "turn-1") == first
    await feed(codex, started(), turn_completed())
    assert codex.mcp_call("github", "turn-1") is None
    assert len(sink.calls) > 0


async def test_tool_items_are_calls_then_results_and_a_search_comes_whole() -> None:
    codex, sink = stream()
    command: JsonObject = {"type": "commandExecution", "id": "c1", "command": "ls"}
    change: JsonObject = {
        "type": "fileChange",
        "id": "f1",
        "changes": [{"path": "a.py", "diff": ""}],
    }
    search: JsonObject = {"type": "webSearch", "id": "w1", "query": "codex"}

    await feed(codex, item("started", command), item("started", change))
    assert codex.file_changes == {"f1": change}
    await feed(
        codex,
        item("completed", {**command, "status": "completed", "aggregatedOutput": "a.py"}),
        item("completed", {**change, "status": "completed"}),
        item("started", search),
        item("completed", search),
    )

    assert codex.file_changes == {}
    assert sink.calls == [
        ("message", ([ToolUseBlock(id="c1", name="Bash", input={"command": "ls"})], None)),
        (
            "message",
            (
                [
                    ToolUseBlock(
                        id="f1",
                        name="Edit",
                        input={"file_path": "a.py", "old_string": "", "new_string": "", "diff": ""},
                    )
                ],
                None,
            ),
        ),
        ("message", ([ToolResultBlock(tool_use_id="c1", content="a.py")], None)),
        ("message", ([ToolResultBlock(tool_use_id="f1", content="Done")], None)),
        ("message", ([ToolUseBlock(id="w1", name="WebSearch", input={"query": "codex"})], None)),
        ("message", ([ToolResultBlock(tool_use_id="w1", content="Searched")], None)),
    ]


async def test_a_steered_message_is_taken_when_codex_echoes_it() -> None:
    codex, sink = stream()
    codex.steered.add("q1")
    echo: JsonObject = {"type": "userMessage", "id": "u9", "clientId": "q1", "content": []}

    await feed(
        codex,
        item("started", echo),
        item("started", {**echo, "id": "u10"}),
        item("started", {"type": "userMessage", "id": "u0", "clientId": None}),
    )

    assert sink.calls == [("message_taken", ("q1", "u9"))]
    assert codex.steered == set()


async def test_the_turn_counts_its_own_tokens_and_the_context_it_filled() -> None:
    codex, sink = stream()
    earlier: JsonObject = {"inputTokens": 5000, "cachedInputTokens": 1000, "outputTokens": 100}

    await feed(codex, usage(earlier, earlier))
    assert codex.context_usage() == ContextUsage(percent=2.55, used=5100, limit=200_000)
    await feed(
        codex,
        started(),
        usage(
            {"inputTokens": 7000, "cachedInputTokens": 2500, "outputTokens": 150},
            {"inputTokens": 2000, "cachedInputTokens": 1500, "outputTokens": 50},
        ),
        usage(
            {
                "inputTokens": 10000,
                "cachedInputTokens": 4000,
                "cacheWriteInputTokens": 500,
                "outputTokens": 400,
            },
            {"inputTokens": 3000, "cachedInputTokens": 1500, "outputTokens": 250},
            window=None,
        ),
        turn_completed(duration_ms=None),
    )

    _, info = sink.calls[-1]
    assert isinstance(info, ResultInfo)
    assert info.duration_ms == 0
    assert info.tokens == TokenUsage(
        input_tokens=1500,
        output_tokens=300,
        cache_read_input_tokens=3000,
        cache_creation_input_tokens=500,
    )
    assert codex.context_usage() == ContextUsage(percent=1.625, used=3250, limit=200_000)


async def test_without_usage_reports_there_are_no_tokens_or_context() -> None:
    codex, sink = stream()

    await feed(codex, started(), turn_completed())

    _, info = sink.calls[-1]
    assert isinstance(info, ResultInfo)
    assert info.tokens == TokenUsage()
    assert codex.context_usage() is None


async def test_a_report_of_another_turn_does_not_start_the_count() -> None:
    codex, _ = stream()
    other = usage({"inputTokens": 9}, {"inputTokens": 9})
    other["params"]["turnId"] = "turn-0"  # type: ignore[index]

    await feed(codex, started(), other)

    assert codex._first_total is None  # pyright: ignore[reportPrivateUsage]


async def test_failed_and_interrupted_turns_say_so() -> None:
    codex, sink = stream()
    error: JsonObject = {"message": "Server overloaded", "codexErrorInfo": "serverOverloaded"}

    await feed(codex, started(), turn_completed("failed", error=error))
    await feed(codex, started(), turn_completed("interrupted"))
    await feed(codex, started(), turn_completed("odd"))
    await feed(codex, started(), turn_completed(""))

    results = [info for kind, info in sink.calls if kind == "result"]
    assert [(r.is_error, r.subtype, r.errors) for r in results] == [  # type: ignore[union-attr]
        (True, "error", ["Server overloaded"]),
        (False, "interrupted", []),
        (False, "odd", []),
        (False, "unknown", []),
    ]


async def test_the_usage_limit_is_reported_once_with_its_window_and_reset() -> None:
    codex, sink = stream()
    resets = 1_900_000_000
    limits = note(
        "account/rateLimits/updated",
        rateLimits={
            "primary": {"usedPercent": 40, "windowDurationMins": 300, "resetsAt": 1},
            "secondary": {"usedPercent": 100, "windowDurationMins": 10080, "resetsAt": resets},
            "planType": None,
        },
    )
    error: JsonObject = {
        "message": "You hit your usage limit",
        "codexErrorInfo": "usageLimitExceeded",
    }

    await feed(
        codex,
        limits,
        note("account/rateLimits/updated", rateLimits={"secondary": None}),
        started(),
        note("error", error=error, willRetry=False, threadId="thread-1", turnId="turn-1"),
        turn_completed("failed", error=error),
    )

    hits = [hit for kind, hit in sink.calls if kind == "limit_hit"]
    assert hits == [
        LimitHit(window="seven_day", resets_at=datetime.fromtimestamp(resets, UTC), cut_off=True)
    ]


async def test_a_limit_without_known_windows_is_still_a_cut_off() -> None:
    codex, sink = stream()
    error: JsonObject = {"message": "limit", "codexErrorInfo": "usageLimitExceeded"}
    limits = note(
        "account/rateLimits/updated",
        rateLimits={"primary": {"usedPercent": 100, "windowDurationMins": 60, "resetsAt": None}},
    )

    await feed(codex, limits, started(), turn_completed("failed", error=error))

    assert ("limit_hit", LimitHit(cut_off=True)) in sink.calls


async def test_retries_and_other_errors() -> None:
    codex, sink = stream()

    await feed(
        codex,
        note("error", error={"message": "Reconnecting 1/5"}, willRetry=True),
        note("error", error={}, willRetry=True),
        note("error", error={"message": "bad", "codexErrorInfo": "badRequest"}, willRetry=False),
    )

    assert sink.calls == [
        ("notice", ("api_retry", "Reconnecting 1/5")),
        ("notice", ("api_retry", "Codex retries.")),
    ]


async def test_notices_for_a_model_switch_and_a_compaction() -> None:
    codex, sink = stream()

    await feed(
        codex,
        note("model/rerouted", threadId="thread-1", fromModel="gpt-6.1-sol", toModel="gpt-5.5"),
        item("completed", {"type": "contextCompaction", "id": "k1"}),
        item("completed", {"type": "plan", "id": "p1", "text": "ignored"}),
        note("thread/status/changed", threadId="thread-1", status={"type": "idle"}),
    )

    assert sink.calls == [
        ("notice", ("model_fallback", "Codex switched from gpt-6.1-sol to gpt-5.5.")),
        ("notice", ("compacted", COMPACTED)),
    ]


async def test_hooks_with_something_to_say_are_shown() -> None:
    codex, sink = stream()

    def hook(status: str, entries: list[str], message: str | None) -> JsonObject:
        return note(
            "hook/completed",
            threadId="thread-1",
            turnId=None,
            run={
                "id": "h1",
                "eventName": "preToolUse",
                "status": status,
                "statusMessage": message,
                "entries": [{"kind": "warning", "text": text} for text in entries],
            },
        )

    await feed(
        codex,
        hook("completed", ["lint ok", ""], None),
        hook("blocked", [], "Blocked rm -rf"),
        hook("stopped", ["stopped"], None),
        hook("completed", [], None),
    )

    assert [call for _, call in sink.calls] == [
        HookOutput(
            hook_id="h1",
            hook_name="PreToolUse",
            hook_event="PreToolUse",
            outcome="success",
            output="lint ok",
        ),
        HookOutput(
            hook_id="h1",
            hook_name="PreToolUse",
            hook_event="PreToolUse",
            outcome="error",
            system_message="Blocked rm -rf",
        ),
        HookOutput(
            hook_id="h1",
            hook_name="PreToolUse",
            hook_event="PreToolUse",
            outcome="cancelled",
            output="stopped",
        ),
    ]


async def test_mcp_servers_are_reported_as_they_start() -> None:
    codex, sink = stream()

    await feed(
        codex,
        note("mcpServer/startupStatus/updated", name="github", status="starting", error=None),
        note("mcpServer/startupStatus/updated", name="db", status="failed", error="no binary"),
        note("mcpServer/startupStatus/updated", name="github", status="ready", error=None),
        note("mcpServer/startupStatus/updated", name="x", status="weird", error=None),
    )

    assert sink.calls[-1] == (
        "connectors",
        [
            McpServer("db", "failed", "no binary"),
            McpServer("github", "connected"),
            McpServer("x", "pending"),
        ],
    )


async def test_another_threads_notifications_are_left_out() -> None:
    codex, sink = stream()

    await codex.handle("item/agentMessage/delta", {"threadId": "subagent", "delta": "x"})

    assert sink.calls == []


async def test_a_limit_with_no_rate_limits_known_is_a_bare_cut_off() -> None:
    codex, sink = stream()
    error: JsonObject = {"message": "limit", "codexErrorInfo": "usageLimitExceeded"}

    await feed(codex, started(), turn_completed("failed", error=error))

    assert ("limit_hit", LimitHit(cut_off=True)) in sink.calls


async def test_rate_limits_are_codexs_usage_windows_as_they_change() -> None:
    codex, sink = stream()
    first = note(
        "account/rateLimits/updated",
        rateLimits={
            "primary": {"usedPercent": 30, "windowDurationMins": 300, "resetsAt": None},
            "secondary": {"usedPercent": 80, "windowDurationMins": 10080, "resetsAt": None},
        },
    )
    sparse = note(
        "account/rateLimits/updated",
        rateLimits={
            "primary": {"usedPercent": 35, "windowDurationMins": 300, "resetsAt": None},
            "secondary": None,
        },
    )

    await feed(codex, first, sparse, note("account/rateLimits/updated", rateLimits={}))

    usages = [info for kind, info in sink.calls if kind == "usage"]
    assert [[(w.minutes, w.utilization) for w in u.windows] for u in usages] == [  # type: ignore[union-attr]
        [(300, 0.3), (10080, 0.8)],
        [(300, 0.35), (10080, 0.8)],
        [(300, 0.35), (10080, 0.8)],
    ]


async def test_the_free_plans_one_window_is_its_30_day_window() -> None:
    """As recorded live (B91): the primary place holds a 43200-minute window."""
    codex, sink = stream()
    resets = 1_794_965_268

    await feed(
        codex,
        note(
            "account/rateLimits/updated",
            rateLimits={
                "limitId": "codex",
                "limitName": None,
                "primary": {"usedPercent": 4, "windowDurationMins": 43200, "resetsAt": resets},
                "secondary": None,
                "credits": {"hasCredits": False, "unlimited": False, "balance": None},
                "planType": "free",
                "rateLimitReachedType": None,
            },
        ),
    )

    assert [info for kind, info in sink.calls if kind == "usage"] == [
        UsageInfo(
            five_hour=None,
            seven_day=None,
            provider="codex",
            windows=[
                EngineWindow(
                    utilization=0.04,
                    resets_at=datetime.fromtimestamp(resets, UTC),
                    minutes=43200,
                )
            ],
        )
    ]


async def test_rate_limits_without_windows_are_no_usage() -> None:
    codex, sink = stream()

    await feed(codex, note("account/rateLimits/updated", rateLimits={"planType": "free"}))

    assert [kind for kind, _ in sink.calls if kind == "usage"] == []
