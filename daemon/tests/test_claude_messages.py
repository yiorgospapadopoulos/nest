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
    RateLimitStatus,
    RateLimitType,
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

from nestd.providers import base
from nestd.providers.claude_messages import TurnOutput, translate
from nestd.providers.claude_thinking import ThinkingTimer
from tests.recording_sink import RecordingSink
from tests.test_claude_thinking import Ticker, start, stop


async def translated(
    message: Message, thinking: ThinkingTimer | None = None, output: TurnOutput | None = None
) -> list[tuple[str, object]]:
    sink = RecordingSink()
    await translate(message, sink, thinking or ThinkingTimer(), output or TurnOutput())
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


@pytest.mark.parametrize("parent", [None, "toolu_agent"])
async def test_the_engines_own_user_text_is_not_shown_as_claudes(parent: str | None) -> None:
    """PL-09: a skill's body, an interruption marker or a subagent's prompt arrive as user
    messages; only their tool results belong in the transcript.
    """
    skill = UserMessage(
        content=[TextBlock("Base directory for this skill: /x\n\n# Skill\nDo things.")],
        uuid="u1",
        parent_tool_use_id=parent,
    )
    mixed = UserMessage(
        content=[
            ToolResultBlock(tool_use_id="t1", content="Launching skill: review"),
            TextBlock("[Request interrupted by user for tool use]"),
        ],
        uuid="u2",
        parent_tool_use_id=parent,
    )

    assert await translated(skill) == []
    assert await translated(mixed) == [
        (
            "message",
            ([base.ToolResultBlock(tool_use_id="t1", content="Launching skill: review")], parent),
        )
    ]


async def test_plain_user_text_is_not_repeated() -> None:
    # The session layer records what the user sent; the engine's echo is dropped.
    assert await translated(UserMessage(content="hello")) == []
    assert await translated(AssistantMessage(content=[], model="m")) == []


def stream(event: dict[str, Any], parent: str | None = None) -> StreamEvent:
    return StreamEvent(uuid="u", session_id="sdk-1", event=event, parent_tool_use_id=parent)


def hook_response(**data: object) -> HookEventMessage:
    fields: dict[str, Any] = {
        "type": "system",
        "subtype": "hook_response",
        "hook_id": "h1",
        "hook_name": "PostToolUse:Edit",
        "hook_event": "PostToolUse",
        "output": "",
        "stdout": "",
        "stderr": "",
        "outcome": "success",
        **data,
    }
    return HookEventMessage(
        subtype="hook_response", data=fields, hook_event_name=str(fields["hook_event"])
    )


TEXT_DELTA = {
    "type": "content_block_delta",
    "index": 0,
    "delta": {"type": "text_delta", "text": "He"},
}


async def test_text_deltas_are_streamed() -> None:
    assert await translated(stream(TEXT_DELTA)) == [("text_delta", "He")]


def thinking_delta(text: str) -> dict[str, Any]:
    return {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "thinking_delta", "thinking": text},
    }


async def test_thinking_streams_as_it_is_written() -> None:
    """B59: as in Claude Code, for the main agent and for subagents."""
    assert await translated(stream(thinking_delta("Let me"))) == [
        ("thinking_delta", ("Let me", None))
    ]
    assert await translated(stream(thinking_delta("Hmm"), parent="toolu_1")) == [
        ("thinking_delta", ("Hmm", "toolu_1"))
    ]


async def test_subagent_text_streams_under_its_tool_call() -> None:
    """B59: a subagent's text, attributed to the Agent call that started it."""
    assert await translated(stream(TEXT_DELTA, parent="toolu_1")) == [
        ("subagent_delta", ("He", "toolu_1"))
    ]


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
        stream({"type": "content_block_delta", "delta": {"type": "thinking_delta"}}),
        stream(
            {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": ""}}
        ),
        stream({"type": "content_block_delta", "delta": {"type": "signature_delta"}}),
        stream({"type": "content_block_delta", "delta": {"type": "text_delta"}}, parent="t"),
        stream({"type": "message_start", "message": {}}),
        SystemMessage(subtype="status", data={}),
        SystemMessage(subtype="status", data={"status": None, "permissionMode": "dontAsk"}),
        HookEventMessage(subtype="hook_started", data={}, hook_event_name="PreToolUse"),
        # A hook that ran quietly, or whose output was context for Claude, shows nothing,
        # as in Claude Code: SessionStart and UserPromptSubmit output goes to Claude.
        hook_response(stdout=""),
        hook_response(stdout='{"hookSpecificOutput": {"additionalContext": "x"}}'),
        hook_response(stdout='{"systemMessage": 3}'),
        hook_response(stdout="lint ok\n", exit_code=0),
        hook_response(stdout="{oops"),
        hook_response(hook_event="SessionStart", stdout="=== REMEMBER ===\nnotes"),
        hook_response(hook_event="UserPromptSubmit", stdout="[14:37 EEST]", exit_code=0),
    ],
)
async def test_other_messages_are_ignored(event: Message) -> None:
    assert await translated(event) == []


@pytest.mark.parametrize(
    ("message", "shown"),
    [
        # The message a hook has for the user, as Claude Code shows it.
        (
            hook_response(stdout='  {"systemMessage": "Formatted 2 files", "continue": true}\n'),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="success",
                system_message="Formatted 2 files",
            ),
        ),
        # A message for the user with output for Claude shows the message only.
        (
            hook_response(
                stdout='{"systemMessage": "Saved", "hookSpecificOutput": {"additionalContext": 1}}'
            ),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="success",
                system_message="Saved",
            ),
        ),
        # A hook that failed shows, even with nothing to say.
        (
            hook_response(outcome="error", stdout="", stderr="", output=""),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="error",
            ),
        ),
        (
            hook_response(outcome="cancelled", stdout="partial"),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="cancelled",
                output="partial",
            ),
        ),
        # An exit code that is not 0 is a failure, whatever the outcome says.
        (
            hook_response(exit_code=1, stdout="bad config"),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="error",
                exit_code=1,
                output="bad config",
            ),
        ),
        # A hook that blocks says why, as a failure, like Claude Code's blocking error.
        (
            hook_response(stdout='{"decision": "block", "reason": "Run the tests first"}'),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="error",
                output="Run the tests first",
            ),
        ),
        (
            hook_response(stdout='{"continue": false, "stopReason": "Out of budget"}'),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="error",
                output="Out of budget",
            ),
        ),
        # A failure says what the hook wrote to stderr, else its other output.
        (
            hook_response(outcome="error", exit_code=2, stdout="x", stderr="Blocked: tests fail\n"),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="error",
                exit_code=2,
                output="Blocked: tests fail",
            ),
        ),
        (
            hook_response(outcome="error", exit_code=1, output="combined"),
            base.HookOutput(
                hook_id="h1",
                hook_name="PostToolUse:Edit",
                hook_event="PostToolUse",
                outcome="error",
                exit_code=1,
                output="combined",
            ),
        ),
        # Fields the engine left out or sent in another form.
        (
            HookEventMessage(
                subtype="hook_response",
                data={
                    "stdout": '{"systemMessage": "hi"}',
                    "outcome": "later",
                    "exit_code": "0",
                    "hook_id": 4,
                },
                hook_event_name="Stop",
            ),
            base.HookOutput(
                hook_event="Stop", hook_name="Stop", outcome="success", system_message="hi"
            ),
        ),
    ],
)
async def test_hook_messages_are_shown(message: HookEventMessage, shown: base.HookOutput) -> None:
    """B59: a hook's message for the user and a hook that failed appear in the transcript,
    as in Claude Code; output a hook gives Claude does not.
    """
    assert await translated(message) == [("hook", shown)]


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


async def test_auto_mode_is_reported() -> None:
    """IMP-06: Claude Code's `auto` mode is one of Nest's modes."""
    message = system("status", status=None, permissionMode="auto")

    assert await translated(message) == [("permission_mode", "auto")]


@pytest.mark.parametrize(("mode", "reported"), [("acceptEdits", True), ("dontAsk", False)])
async def test_init_reports_the_mode_the_run_works_in(mode: str, reported: bool) -> None:
    """IMP-06: a run opened without a mode works in Claude Code's own `defaultMode`."""
    message = SystemMessage(subtype="init", data={"session_id": "sdk-1", "permissionMode": mode})

    calls = await translated(message)

    assert (("permission_mode", mode) in calls) is reported
    assert calls[:2] == [("provider_session_id", "sdk-1"), ("connectors", [])]


def echo(content: str | list[Any], uuid: str | None = "msg-1") -> UserMessage:
    """The engine's echo of a user message Nest sent (`--replay-user-messages`)."""
    return UserMessage(content=content, uuid=uuid)


def awaiting() -> TurnOutput:
    output = TurnOutput()
    output.awaiting_replay = True
    return output


@pytest.mark.parametrize(
    "content", [[TextBlock("Fix the bug")], [TextBlock("Look"), TextBlock("at this")], "/cost"]
)
async def test_the_echo_of_a_sent_message_gives_its_checkpoint_only(
    content: str | list[Any],
) -> None:
    """IMP-02: the echo carries the id files can be restored to; the session already shows
    the message, so it is not repeated.
    """
    output = awaiting()

    first = await translated(echo(content), output=output)
    again = await translated(echo([TextBlock("later text")], "msg-2"), output=output)

    assert first == [("checkpoint", "msg-1")]
    assert output.awaiting_replay is False
    # Only the first echo after a send is the message Nest sent; a later user text is
    # the engine's own, never shown as Claude's (PL-09).
    assert again == []


@pytest.mark.parametrize(
    "message",
    [
        UserMessage(content=[ToolResultBlock(tool_use_id="t1", content="ok")], uuid="u"),
        UserMessage(content=[TextBlock("subagent prompt")], uuid="u", parent_tool_use_id="t1"),
        echo([TextBlock("no id")], uuid=None),
        echo("<local-command-stdout>Total cost: $0</local-command-stdout>"),
    ],
)
async def test_other_user_messages_are_not_the_echo(message: UserMessage) -> None:
    output = awaiting()

    calls = await translated(message, output=output)

    assert all(name != "checkpoint" for name, _ in calls)
    assert output.awaiting_replay is True


async def test_a_turns_end_stops_waiting_for_the_echo() -> None:
    output = awaiting()

    await translated(command_result(None, num_turns=1), output=output)

    assert output.awaiting_replay is False


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


def limit_event(
    status: RateLimitStatus,
    resets_at: int | None = None,
    rate_limit_type: RateLimitType | None = None,
    overage_status: RateLimitStatus | None = None,
    raw: dict[str, Any] | None = None,
) -> RateLimitEvent:
    info = RateLimitInfo(
        status=status,
        resets_at=resets_at,
        rate_limit_type=rate_limit_type,
        overage_status=overage_status,
        raw=raw or {},
    )
    return RateLimitEvent(rate_limit_info=info, uuid="u", session_id="sdk-1")


async def test_a_rejected_rate_limit_reports_the_limit_with_its_window_and_reset() -> None:
    """B78: the engine refuses requests until the window resets."""
    event = limit_event(status="rejected", resets_at=1791300600, rate_limit_type="five_hour")

    assert await translated(event) == [
        (
            "limit_hit",
            base.LimitHit(window="five_hour", resets_at=datetime.fromtimestamp(1791300600, UTC)),
        )
    ]


async def test_a_rejected_rate_limit_still_reports_its_usage_windows() -> None:
    raw = {"unifiedWindows": {"seven_day": {"utilization": 1.0, "resetsAt": 1791802800}}}
    event = limit_event(status="rejected", rate_limit_type="seven_day", raw=raw)

    calls = await translated(event)

    assert [name for name, _ in calls] == ["usage", "limit_hit"]
    assert calls[1] == ("limit_hit", base.LimitHit(window="seven_day"))


async def test_a_rejected_rate_limit_of_an_unknown_window_reports_no_window() -> None:
    event = limit_event(status="rejected", resets_at=1791300600)
    event.rate_limit_info.rate_limit_type = "a_new_window"  # type: ignore[assignment]

    (call,) = await translated(event)

    assert call == (
        "limit_hit",
        base.LimitHit(window=None, resets_at=datetime.fromtimestamp(1791300600, UTC)),
    )


@pytest.mark.parametrize(
    "info",
    [
        {"status": "allowed", "rate_limit_type": "five_hour", "resets_at": 1791300600},
        {"status": "allowed_warning", "rate_limit_type": "seven_day"},
        # Over the plan's limit, but extra usage goes on paying for the requests.
        {"status": "rejected", "rate_limit_type": "five_hour", "overage_status": "allowed"},
        {"status": "rejected", "overage_status": "allowed_warning"},
    ],
)
async def test_rate_limits_that_still_allow_requests_report_no_limit(info: dict[str, Any]) -> None:
    assert await translated(limit_event(**info)) == []


async def test_a_message_cut_off_by_the_rate_limit_reports_the_limit() -> None:
    message = AssistantMessage(
        content=[TextBlock("You've hit your limit")], model="m", error="rate_limit"
    )

    assert await translated(message) == [
        ("message", ([base.TextBlock(text="You've hit your limit")], None)),
        ("limit_hit", base.LimitHit(cut_off=True)),
    ]


async def test_a_message_cut_off_by_the_rate_limit_without_content_still_reports_it() -> None:
    message = AssistantMessage(content=[], model="m", error="rate_limit")

    assert await translated(message) == [("limit_hit", base.LimitHit(cut_off=True))]


async def test_other_message_errors_report_no_limit() -> None:
    message = AssistantMessage(content=[TextBlock("Server error")], model="m", error="server_error")

    assert [name for name, _ in await translated(message)] == ["message"]


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


async def test_results_without_errors() -> None:
    """B59: the cost of a turn is not reported; the context meter replaces it."""
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
        base.ResultInfo(is_error=False, subtype="success", duration_ms=5, num_turns=1, errors=[]),
    )


def command_result(result: str | None, num_turns: int = 0, is_error: bool = False) -> ResultMessage:
    """How Claude Code ends a turn: a local command's has no model call (`num_turns` 0)."""
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=0,
        is_error=is_error,
        num_turns=num_turns,
        session_id="sdk-1",
        result=result,
    )


@pytest.mark.parametrize(
    ("content", "shown"),
    [
        (
            "<local-command-stdout>Total cost: $0.12\nTotal duration: 3s</local-command-stdout>",
            "Total cost: $0.12\nTotal duration: 3s",
        ),
        (
            "<local-command-stderr>/voice isn't available in this session.</local-command-stderr>",
            "/voice isn't available in this session.",
        ),
        (
            "<local-command-stdout>Set model</local-command-stdout>"
            "<local-command-stderr>  but not saved  </local-command-stderr>",
            "Set model\nbut not saved",
        ),
    ],
)
async def test_local_command_output_is_shown_as_a_notice(content: str, shown: str) -> None:
    """PL-13: /cost, /context and the like answer without the model, as a user message."""
    assert await translated(UserMessage(content=content)) == [("notice", ("command_output", shown))]


@pytest.mark.parametrize(
    "content",
    [
        "Fix the bug",
        "<local-command-stdout>  </local-command-stdout>",
        "<local-command-caveat>Caveat: generated by local commands</local-command-caveat>",
        "<command-name>/cost</command-name>",
    ],
)
async def test_other_plain_user_text_is_not_shown_again(content: str) -> None:
    """The user's own prompt and Claude Code's records are not command output."""
    assert await translated(UserMessage(content=content)) == []


async def test_the_sdk_form_of_command_output_is_shown_as_a_notice() -> None:
    message = system("local_command_output", content="Voice mode is on")

    assert await translated(message) == [("notice", ("command_output", "Voice mode is on"))]


@pytest.mark.parametrize("content", [" ", None, 3])
async def test_the_sdk_form_without_output_shows_nothing(content: object) -> None:
    assert await translated(system("local_command_output", content=content)) == []


async def test_a_command_result_without_any_text_shown_becomes_a_notice() -> None:
    output = TurnOutput()

    first = await translated(command_result("Compacted. ctrl+o to see"), output=output)
    # Each turn starts with nothing shown.
    second = await translated(command_result("Again"), output=output)

    assert first[0] == ("notice", ("command_output", "Compacted. ctrl+o to see"))
    assert [name for name, _ in first] == ["notice", "provider_session_id", "result"]
    assert second[0] == ("notice", ("command_output", "Again"))


@pytest.mark.parametrize(
    "shown",
    [
        UserMessage(content="<local-command-stdout>Total cost: $0.12</local-command-stdout>"),
        system("local_command_output", content="Total cost: $0.12"),
        # Claude Code also sends command output as the assistant's text.
        AssistantMessage(content=[TextBlock("Total cost: $0.12")], model="<synthetic>"),
        system("compact_boundary"),
    ],
)
async def test_a_command_result_already_shown_is_not_repeated(shown: Message) -> None:
    output = TurnOutput()
    await translated(shown, output=output)

    calls = await translated(command_result("Total cost: $0.12"), output=output)

    assert [name for name, _ in calls] == ["provider_session_id", "result"]


@pytest.mark.parametrize(
    "result",
    [
        command_result("The answer", num_turns=1),
        command_result("Prompt is too long", is_error=True),
        command_result(None),
        command_result("  "),
    ],
)
async def test_model_turns_errors_and_empty_results_add_no_notice(result: ResultMessage) -> None:
    """A model turn's result repeats text the agent streamed; an error shows as the state."""
    output = TurnOutput()
    # A subagent's text is not the answer the user saw.
    await translated(
        AssistantMessage(content=[TextBlock("x")], model="m", parent_tool_use_id="p"), output=output
    )

    calls = await translated(result, output=output)

    assert [name for name, _ in calls] == ["provider_session_id", "result"]


SUBAGENT_USAGE: dict[str, Any] = {
    "input_tokens": 3,
    "output_tokens": 40,
    "cache_creation_input_tokens": 500,
    "cache_read_input_tokens": 6000,
    "service_tier": "standard",
}


async def test_a_subagent_reply_reports_its_tokens_by_message_id() -> None:
    """The turn's result counts only the main chat; a subagent's replies say their own."""
    message = AssistantMessage(
        content=[TextBlock("Found it")],
        model="m",
        parent_tool_use_id="toolu_1",
        usage=SUBAGENT_USAGE,
        message_id="msg_1",
    )

    assert await translated(message) == [
        ("message", ([base.TextBlock(text="Found it")], "toolu_1")),
        (
            "subagent_usage",
            (
                "msg_1",
                base.TokenUsage(
                    input_tokens=3,
                    output_tokens=40,
                    cache_creation_input_tokens=500,
                    cache_read_input_tokens=6000,
                ),
            ),
        ),
    ]


async def test_a_subagent_reply_without_content_still_reports_its_tokens() -> None:
    message = AssistantMessage(
        content=[], model="m", parent_tool_use_id="toolu_1", usage={}, message_id="msg_2"
    )

    assert await translated(message) == [("subagent_usage", ("msg_2", base.TokenUsage()))]


@pytest.mark.parametrize(
    "message",
    [
        # The main chat's replies: its result counts them.
        AssistantMessage(content=[], model="m", usage=SUBAGENT_USAGE, message_id="msg_1"),
        AssistantMessage(content=[], model="m", parent_tool_use_id="t", message_id="msg_1"),
        AssistantMessage(content=[], model="m", parent_tool_use_id="t", usage=SUBAGENT_USAGE),
    ],
)
async def test_tokens_are_reported_only_for_subagent_replies_with_usage_and_an_id(
    message: AssistantMessage,
) -> None:
    assert await translated(message) == []
