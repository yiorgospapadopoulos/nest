"""What the run reports about its mode, its thinking and the user's messages (B34: BUG-90,
BUG-91, BUG-93).
"""

from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import SystemMessage, TextBlock, UserMessage

from harness.providers.base import SessionSpec
from harness.providers.claude_messages import TurnOutput, translate
from harness.providers.claude_thinking import ThinkingTimer
from tests.async_support import until
from tests.recording_sink import RecordingSink
from tests.test_claude_messages import stream
from tests.test_claude_provider import Opened
from tests.test_claude_thinking import Ticker, start, stop


def init(mode: str) -> SystemMessage:
    return SystemMessage(subtype="init", data={"session_id": "sdk-1", "permissionMode": mode})


def status(mode: str) -> SystemMessage:
    return SystemMessage(subtype="status", data={"status": None, "permissionMode": mode})


def modes(sink: RecordingSink) -> list[object]:
    return [value for name, value in sink.calls if name == "permission_mode"]


async def test_the_start_up_report_is_ignored_once_harness_set_the_mode(tmp_path: Path) -> None:
    """BUG-90: the mode chosen while the first message was on its way stays."""
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "acceptEdits"))

    await run.set_permission_mode("plan")
    client.push(init("acceptEdits"), status("default"))
    await until(lambda: len(modes(opened.sink)) == 1)
    await run.close()

    assert client.calls == [("set_permission_mode", "plan")]
    # A later switch the engine makes itself is still reported.
    assert modes(opened.sink) == ["default"]


async def test_the_start_up_report_counts_until_harness_sets_a_mode(tmp_path: Path) -> None:
    """IMP-06: a run opened without a mode works in Claude Code's own."""
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, None))

    client.push(init("bypassPermissions"))
    await until(lambda: len(modes(opened.sink)) == 1)
    await run.close()

    assert modes(opened.sink) == ["bypassPermissions"]


def test_a_new_response_ends_thinking_that_never_stopped() -> None:
    """BUG-91: blocks a new response drops are reported stopped."""
    timer = ThinkingTimer(Ticker())

    assert timer.stream(start(0)) is True
    assert timer.stream({"type": "message_start", "message": {}}) is False
    assert timer.stream({"type": "message_start", "message": {}}) is None
    assert timer.stream(start(1)) is True
    assert timer.stream(stop(1)) is False


async def test_the_reader_reports_thinking_ended_by_a_new_response() -> None:
    sink, timer, output = RecordingSink(), ThinkingTimer(Ticker()), TurnOutput()

    new_response: dict[str, Any] = {"type": "message_start", "message": {}}
    for event in (start(0), new_response):
        await translate(stream(event), sink, timer, output)

    assert sink.calls == [("thinking", True), ("thinking", False)]


def awaiting() -> TurnOutput:
    output = TurnOutput()
    output.awaiting_replay = True
    return output


@pytest.mark.parametrize(
    "origin", [{"kind": "task-notification"}, {"kind": "peer"}, {"kind": "some-new-kind"}]
)
async def test_an_injected_message_is_not_the_echo_of_the_users(origin: dict[str, Any]) -> None:
    """BUG-93: a task notification or scheduled prompt arriving first is not the user's
    message, so its id is no checkpoint of it.
    """
    sink, output = RecordingSink(), awaiting()
    injected = UserMessage(content=[TextBlock("<task-notification>")], uuid="inj-1")
    injected.origin = origin  # type: ignore[assignment]
    echo = UserMessage(content=[TextBlock("Fix the bug")], uuid="msg-1")

    await translate(injected, sink, ThinkingTimer(), output)
    await translate(echo, sink, ThinkingTimer(), output)

    assert [call for call in sink.calls if call[0] == "checkpoint"] == [("checkpoint", "msg-1")]


async def test_the_echo_may_say_it_came_from_the_user() -> None:
    sink, output = RecordingSink(), awaiting()
    echo = UserMessage(content=[TextBlock("Fix the bug")], uuid="msg-1", origin={"kind": "human"})

    await translate(echo, sink, ThinkingTimer(), output)

    assert sink.calls == [("checkpoint", "msg-1")]
