"""A subagent's own transcript from the stored events, split by its calls (B46)."""

from datetime import UTC, datetime

from pydantic import JsonValue

from nestd.events import types
from nestd.events.models import Event
from nestd.providers.base import (
    AgentTask,
    MessageBlock,
    TextBlock,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.tracking.transcripts import AgentMessage, AgentWork, agent_work

TS = datetime(2026, 10, 16, tzinfo=UTC)


class Log:
    def __init__(self) -> None:
        self.events: list[Event] = []

    def add(self, event_type: str, payload: dict[str, JsonValue]) -> int:
        event_id = len(self.events) + 1
        self.events.append(
            Event(id=event_id, type=event_type, ts=TS, session_id="s", payload=payload)
        )
        return event_id

    def message(self, parent: str | None, *blocks: MessageBlock) -> int:
        return self.add(
            types.SESSION_MESSAGE,
            {
                "blocks": [block.model_dump(mode="json") for block in blocks],
                "parent_tool_use_id": parent,
            },
        )

    def task(self, update: AgentTask) -> None:
        self.add(types.SESSION_AGENT_TASK, update.model_dump(mode="json"))


def call(call_id: str, prompt: str, *, background: bool = False) -> ToolUseBlock:
    fields: dict[str, JsonValue] = {"subagent_type": "scribe", "prompt": prompt}
    if background:
        fields["run_in_background"] = True
    return ToolUseBlock(id=call_id, name="Agent", input=fields)


def send(call_id: str, to: str, message: str) -> ToolUseBlock:
    return ToolUseBlock(
        id=call_id, name="SendMessage", input={"to": to, "message": message, "summary": "go"}
    )


def read(step: str) -> ToolUseBlock:
    return ToolUseBlock(id=step, name="Read", input={"file_path": "a.py"})


def test_a_foreground_call_has_its_prompt_messages_and_report() -> None:
    log = Log()
    log.add(types.SESSION_USER_MESSAGE, {"text": "@scribe go"})
    log.message(None, TextBlock(text="Calling."), call("a1", "Pick an animal"))
    first = log.message("a1", read("r1"))
    second = log.message("a1", ToolResultBlock(tool_use_id="r1", content="code"))
    log.message("other", TextBlock(text="someone else"))
    log.message(None, ToolResultBlock(tool_use_id="a1", content="ok\nagentId: ae7"))

    (work,) = agent_work(log.events, "a1", ["a1"])

    assert work == AgentWork(
        tool_use_id="a1",
        prompt="Pick an animal",
        messages=[
            AgentMessage(event_id=first, ts=TS, blocks=[read("r1")]),
            AgentMessage(
                event_id=second, ts=TS, blocks=[ToolResultBlock(tool_use_id="r1", content="code")]
            ),
        ],
        report="ok\nagentId: ae7",
    )


def test_a_continued_agent_is_split_by_its_calls() -> None:
    log = Log()
    log.message(None, call("a1", "Pick an animal"))
    log.message("a1", TextBlock(text="picked"))
    log.message(None, ToolResultBlock(tool_use_id="a1", content="ok"))
    log.message(None, send("s1", "ae7", "Which one?"))
    log.message(None, ToolResultBlock(tool_use_id="s1", content='{"success":true}'))
    log.task(AgentTask(task_id="ae7", phase="started", tool_use_id="s1", background=True))
    # Its messages keep the first call's id.
    later = log.message("a1", TextBlock(text="platypus"))
    log.task(
        AgentTask(
            task_id="ae7",
            phase="finished",
            tool_use_id="s1",
            status="completed",
            summary="platypus",
        )
    )

    first, again = agent_work(log.events, "a1", ["a1", "s1"])

    assert [m.blocks for m in first.messages] == [[TextBlock(text="picked")]]
    assert (first.prompt, first.report) == ("Pick an animal", "ok")
    assert again == AgentWork(
        tool_use_id="s1",
        prompt="Which one?",
        messages=[AgentMessage(event_id=later, ts=TS, blocks=[TextBlock(text="platypus")])],
        # The SendMessage result only says it resumed: the report is the task's summary.
        report="platypus",
    )


def test_a_background_call_reports_when_its_task_ends() -> None:
    log = Log()
    log.message(None, call("a1", "Look", background=True))
    log.message(None, ToolResultBlock(tool_use_id="a1", content="Async agent launched"))
    log.task(AgentTask(task_id="ae7", phase="started", tool_use_id="a1", background=True))

    (running,) = agent_work(log.events, "a1", ["a1"])
    log.task(AgentTask(task_id="ae7", phase="finished", status="completed"))
    log.task(AgentTask(task_id="ae7", phase="finished", tool_use_id="a1", summary="found"))

    (done,) = agent_work(log.events, "a1", ["a1"])

    assert (running.report, done.report) == (None, "found")


def test_a_call_that_failed_reports_its_error() -> None:
    log = Log()
    log.message(None, send("s1", "ae7", "More"))
    log.message(None, ToolResultBlock(tool_use_id="s1", content="no such agent", is_error=True))

    (work,) = agent_work(log.events, "a1", ["s1"])

    assert (work.prompt, work.report, work.messages) == ("More", "no such agent", [])


def test_a_call_still_running_or_unknown() -> None:
    log = Log()
    # Messages before any call it knows, from a stream it did not see start.
    log.message("a1", TextBlock(text="early"))
    log.message(None, ToolUseBlock(id="a1", name="Agent", input={"prompt": 3}))
    log.message(None, ToolResultBlock(tool_use_id="x9", content="unrelated"))

    assert agent_work(log.events, "a1", ["a1", "s9"]) == [
        AgentWork(tool_use_id="a1", prompt=None, messages=[], report=None)
    ]
