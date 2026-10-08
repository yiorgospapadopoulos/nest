from datetime import UTC, datetime
from typing import Any

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ConversationResetMessage,
    HookEventMessage,
    Message,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    ServerToolResultBlock,
    ServerToolUseBlock,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from harness.providers import base
from harness.providers.claude_messages import translate
from harness.providers.claude_thinking import ThinkingTimer
from tests.recording_sink import RecordingSink
from tests.test_claude_thinking import Ticker, start, stop


async def translated(
    message: Message, thinking: ThinkingTimer | None = None
) -> list[tuple[str, object]]:
    sink = RecordingSink()
    await translate(message, sink, thinking or ThinkingTimer())
    return sink.calls


async def test_init_reports_the_provider_session_id() -> None:
    message = SystemMessage(subtype="init", data={"session_id": "sdk-1", "model": "m"})

    assert await translated(message) == [("provider_session_id", "sdk-1"), ("connectors", [])]


async def test_init_reports_the_mcp_servers_and_skips_malformed_entries() -> None:
    servers: list[Any] = [
        {"name": "claude.ai Gmail", "status": "connected"},
        {"name": "plugin:engineering:github", "status": "needs-auth", "extra": 1},
        {"name": "no-status"},
        {"status": "connected"},
        {"name": 3, "status": "connected"},
        {"name": "bad-error", "status": "failed", "error": 5},
        {"name": "local-db", "status": "failed", "error": "spawn ENOENT"},
        "nonsense",
    ]
    message = SystemMessage(subtype="init", data={"session_id": "sdk-1", "mcp_servers": servers})

    assert (await translated(message))[1] == (
        "connectors",
        [
            base.McpServer("claude.ai Gmail", "connected"),
            base.McpServer("plugin:engineering:github", "needs-auth"),
            base.McpServer("local-db", "failed", "spawn ENOENT"),
        ],
    )


async def test_an_init_without_a_server_list_reports_none() -> None:
    message = SystemMessage(subtype="init", data={"session_id": "sdk-1", "mcp_servers": "x"})

    assert (await translated(message))[1] == ("connectors", [])


async def test_assistant_blocks_are_normalized() -> None:
    message = AssistantMessage(
        content=[
            TextBlock("Hello"),
            ThinkingBlock(thinking="hmm", signature="sig"),
            ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}),
            ServerToolUseBlock(id="s1", name="web_search", input={"query": "x"}),
        ],
        model="m",
        parent_tool_use_id="parent",
    )

    assert await translated(message) == [
        (
            "message",
            (
                [
                    base.TextBlock(text="Hello"),
                    base.ThinkingBlock(text="hmm"),
                    base.ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}),
                    base.ToolUseBlock(id="s1", name="web_search", input={"query": "x"}),
                ],
                "parent",
            ),
        )
    ]


async def test_tool_results_become_text() -> None:
    content: list[dict[str, Any]] = [
        {"type": "text", "text": "line 1"},
        {"type": "image", "source": {}},
        {"type": "text", "text": "line 2"},
    ]
    message = UserMessage(
        content=[
            ToolResultBlock(tool_use_id="t1", content="ok"),
            ToolResultBlock(tool_use_id="t2", content=content, is_error=True),
            ToolResultBlock(tool_use_id="t3"),
            ServerToolResultBlock(tool_use_id="s1", content={"type": "web_search_result"}),
        ]
    )

    assert await translated(message) == [
        (
            "message",
            (
                [
                    base.ToolResultBlock(tool_use_id="t1", content="ok"),
                    base.ToolResultBlock(
                        tool_use_id="t2", content="line 1\n[image]\nline 2", is_error=True
                    ),
                    base.ToolResultBlock(tool_use_id="t3", content=""),
                    base.ToolResultBlock(tool_use_id="s1", content='{"type": "web_search_result"}'),
                ],
                None,
            ),
        )
    ]


async def test_plain_user_text_is_not_repeated() -> None:
    # The session layer records what the user sent; the engine's echo is dropped.
    assert await translated(UserMessage(content="hello")) == []
    assert await translated(AssistantMessage(content=[], model="m")) == []


def stream(event: dict[str, Any], parent: str | None = None) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="sdk-1", event=event, parent_tool_use_id=parent)


TEXT_DELTA = {
    "type": "content_block_delta",
    "index": 0,
    "delta": {"type": "text_delta", "text": "He"},
}


async def test_text_deltas_are_streamed() -> None:
    assert await translated(stream(TEXT_DELTA)) == [("text_delta", "He")]


async def test_the_main_agent_thinking_is_reported_as_it_starts_and_ends() -> None:
    timer = ThinkingTimer(Ticker())

    assert await translated(stream(start(0)), timer) == [("thinking", True)]
    assert await translated(stream(stop(0)), timer) == [("thinking", False)]
    assert await translated(stream(start(1), parent="subagent"), timer) == []


async def test_main_agent_thinking_blocks_carry_how_long_they_took() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)
    await translated(stream(start(0)), timer)
    time.now += 8
    await translated(stream(stop(0)), timer)
    thought = ThinkingBlock(thinking="hmm", signature="sig")

    main = await translated(AssistantMessage(content=[thought, TextBlock("Hi")], model="m"), timer)
    time.now += 3
    # A block without stream timing counts from the content before it.
    again = await translated(AssistantMessage(content=[thought], model="m"), timer)
    sub = await translated(
        AssistantMessage(content=[thought], model="m", parent_tool_use_id="p"), timer
    )

    assert main == [
        (
            "message",
            ([base.ThinkingBlock(text="hmm", duration_ms=8000), base.TextBlock(text="Hi")], None),
        )
    ]
    assert again == [("message", ([base.ThinkingBlock(text="hmm", duration_ms=3000)], None))]
    assert sub == [("message", ([base.ThinkingBlock(text="hmm")], "p"))]


async def test_a_result_ends_the_turns_thinking_timings() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)
    timer.mark()
    await translated(
        ResultMessage(
            subtype="success",
            duration_ms=1,
            duration_api_ms=1,
            is_error=False,
            num_turns=1,
            session_id="sdk-1",
        ),
        timer,
    )
    time.now += 5
    thought = ThinkingBlock(thinking="", signature="sig")

    calls = await translated(AssistantMessage(content=[thought], model="m"), timer)

    assert calls == [("message", ([base.ThinkingBlock(text="")], None))]


@pytest.mark.parametrize(
    "event",
    [
        stream(TEXT_DELTA, parent="subagent"),
        stream({"type": "content_block_delta", "delta": {"type": "thinking_delta"}}),
        stream({"type": "message_start", "message": {}}),
        SystemMessage(subtype="status", data={}),
        SystemMessage(subtype="status", data={"status": None, "permissionMode": "auto"}),
        HookEventMessage(subtype="hook_started", data={}, hook_event_name="PreToolUse"),
    ],
)
async def test_other_messages_are_ignored(event: Message) -> None:
    assert await translated(event) == []


def system(subtype: str, **data: object) -> SystemMessage:
    return SystemMessage(subtype=subtype, data={"type": "system", "subtype": subtype, **data})


@pytest.mark.parametrize(
    ("message", "notice"),
    [
        (
            system("compact_boundary", compact_metadata={"trigger": "auto", "pre_tokens": 9}),
            ("compacted", "Conversation compacted"),
        ),
        (
            ConversationResetMessage(new_conversation_id="c2", uuid="u", session_id="sdk-1"),
            ("cleared", "Context cleared"),
        ),
        (
            system(
                "model_fallback",
                trigger="overloaded",
                original_model="claude-opus-5",
                fallback_model="claude-sonnet-5",
                content="Opus is overloaded; using Sonnet",
            ),
            ("model_fallback", "Opus is overloaded; using Sonnet"),
        ),
        (
            system("model_fallback", fallback_model="claude-sonnet-5"),
            ("model_fallback", "Switched to claude-sonnet-5"),
        ),
        (system("model_fallback"), ("model_fallback", "Switched to another model")),
        (
            system("api_retry", attempt=1, max_retries=10, error_status=529, error="overloaded"),
            ("api_retry", "API error (overloaded), retrying"),
        ),
        (system("api_retry", attempt=2, error=None), ("api_retry", "API error, retrying")),
    ],
)
async def test_engine_notices_are_reported(message: Message, notice: tuple[str, str]) -> None:
    """BUG-41, BUG-44: what Claude Code shows in its transcript is not dropped."""
    assert await translated(message) == [("notice", notice)]


async def test_a_permission_mode_the_engine_switched_to_is_reported() -> None:
    """BUG-43: such as leaving plan mode, or a mode change made by a hook."""
    message = system("status", status=None, permissionMode="plan")

    assert await translated(message) == [("permission_mode", "plan")]


def rate_limit(raw: dict[str, Any]) -> RateLimitEvent:
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(status="allowed", raw=raw), uuid="u", session_id="sdk-1"
    )


async def test_rate_limits_map_to_usage_windows() -> None:
    raw = {
        "status": "allowed",
        "unifiedWindows": {
            "five_hour": {"utilization": 0.3, "resetsAt": 1791300600},
            "seven_day": {"utilization": 0.06, "resetsAt": 1791802800},
        },
    }

    assert await translated(rate_limit(raw)) == [
        (
            "usage",
            base.UsageInfo(
                five_hour=base.UsageWindow(
                    utilization=0.3, resets_at=datetime.fromtimestamp(1791300600, UTC)
                ),
                seven_day=base.UsageWindow(
                    utilization=0.06, resets_at=datetime.fromtimestamp(1791802800, UTC)
                ),
            ),
        )
    ]


async def test_partial_usage_windows() -> None:
    raw = {"unifiedWindows": {"five_hour": {"utilization": 1}}}

    assert await translated(rate_limit(raw)) == [
        (
            "usage",
            base.UsageInfo(
                five_hour=base.UsageWindow(utilization=1.0, resets_at=None), seven_day=None
            ),
        )
    ]


@pytest.mark.parametrize(
    "raw",
    [
        {"status": "allowed"},
        {"unifiedWindows": {}},
        {"unifiedWindows": {"five_hour": {"resetsAt": 1}}},
        {"unifiedWindows": "nonsense"},
    ],
)
async def test_rate_limits_without_usable_windows_are_skipped(raw: dict[str, Any]) -> None:
    assert await translated(rate_limit(raw)) == []


async def test_results_report_the_turn_and_the_session_id() -> None:
    message = ResultMessage(
        subtype="error_during_execution",
        duration_ms=1200,
        duration_api_ms=900,
        is_error=True,
        num_turns=3,
        session_id="sdk-2",
        total_cost_usd=0.25,
        errors=["boom"],
    )

    assert await translated(message) == [
        ("provider_session_id", "sdk-2"),
        (
            "result",
            base.ResultInfo(
                is_error=True,
                subtype="error_during_execution",
                duration_ms=1200,
                num_turns=3,
                cost_usd=0.25,
                errors=["boom"],
            ),
        ),
    ]


async def test_results_carry_the_turns_token_usage() -> None:
    message = ResultMessage(
        subtype="success",
        duration_ms=5,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id="sdk-2",
        usage={
            "input_tokens": 10,
            "output_tokens": 5,
            "cache_creation_input_tokens": None,
            "cache_read_input_tokens": 100,
            "server_tool_use": {"web_search_requests": 0},
        },
    )

    (_, (_, info)) = await translated(message)

    assert isinstance(info, base.ResultInfo)
    assert info.tokens == base.TokenUsage(
        input_tokens=10, output_tokens=5, cache_creation_input_tokens=0, cache_read_input_tokens=100
    )


async def test_results_without_errors_or_cost() -> None:
    message = ResultMessage(
        subtype="success",
        duration_ms=5,
        duration_api_ms=5,
        is_error=False,
        num_turns=1,
        session_id="sdk-2",
    )

    calls = await translated(message)

    assert calls[1] == (
        "result",
        base.ResultInfo(
            is_error=False, subtype="success", duration_ms=5, num_turns=1, cost_usd=None, errors=[]
        ),
    )
