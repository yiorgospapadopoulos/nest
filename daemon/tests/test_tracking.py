from datetime import UTC, datetime, timedelta

import pytest
from pydantic import JsonValue

from nestd.events.models import Event
from nestd.tracking.agents import MAX_STEPS, Change
from nestd.tracking.steps import short_arg, short_result
from nestd.tracking.tracker import SessionTracker
from tests.tracking_fixture import (
    AGENT_ID,
    ROOT,
    create_task,
    message,
    start_agent_message,
    text,
    tool_result,
    tool_use,
    transcript,
    update_task,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


class Feed:
    def __init__(self) -> None:
        self.tracker = SessionTracker()
        self.next_id = 1

    def apply(self, event_type: str, payload: dict[str, JsonValue]) -> tuple[bool, Change]:
        event = Event(
            id=self.next_id,
            type=event_type,
            ts=T0 + timedelta(seconds=self.next_id),
            session_id="s1",
            payload=payload,
        )
        self.next_id += 1
        return self.tracker.apply(event)

    def messages(self, *payloads: dict[str, JsonValue]) -> None:
        for payload in payloads:
            self.apply("session.message", payload)

    def state(self, state: str) -> tuple[bool, Change]:
        return self.apply("session.state", {"state": state, "error": None})

    def tasks(self) -> list[dict[str, JsonValue]]:
        return [task.model_dump(mode="json") for task in self.tracker.tasks.snapshot()]

    def agents(self) -> list[dict[str, JsonValue]]:
        return [agent.model_dump(mode="json") for agent in self.tracker.agents.snapshot()]

    def agent(self, agent_id: str) -> dict[str, JsonValue]:
        return next(a for a in self.agents() if a["id"] == agent_id)


def at(seconds: int) -> str:
    return (T0 + timedelta(seconds=seconds)).isoformat().replace("+00:00", "Z")


def test_a_real_transcript_yields_tasks_agents_and_a_summary() -> None:
    feed = Feed()
    for event_type, payload in transcript():
        feed.apply(event_type, payload)

    assert feed.tasks() == [
        {
            "id": "1",
            "subject": "Read CLAUDE.md",
            "description": "About Read CLAUDE.md",
            "active_form": "Reading CLAUDE.md",
            "status": "completed",
        },
        {
            "id": "2",
            "subject": "Write summary.txt",
            "description": "About Write summary.txt",
            "active_form": "Writing summary.txt",
            "status": "completed",
        },
    ]
    main, explore = feed.agents()
    assert {k: v for k, v in main.items() if k != "steps"} == {
        "id": "main",
        "name": "main",
        "description": None,
        "status": "done",
        "activity": None,
        "started_at": at(1),
        "finished_at": at(25),
    }
    assert main["steps"] == [
        {
            "id": "toolu_create1",
            "tool": "TaskCreate",
            "arg": "Read CLAUDE.md",
            "result": "Task #1 created successfully: Read CLAUDE.md",
        },
        {
            "id": "toolu_create2",
            "tool": "TaskCreate",
            "arg": "Write summary.txt",
            "result": "Task #2 created successfully: Write summary.txt",
        },
        {"id": "toolu_u1", "tool": "TaskUpdate", "arg": "1", "result": "Updated task #1 status"},
        {
            "id": AGENT_ID,
            "tool": "Agent",
            "arg": "Read CLAUDE.md file",
            "result": "[Subagent hand-back] The file says: Demo repo.",
        },
        {"id": "toolu_u2", "tool": "TaskUpdate", "arg": "1", "result": "Updated task #1 status"},
        {
            "id": "toolu_write",
            "tool": "Write",
            "arg": "summary.txt",
            "result": f"File created successfully at: {ROOT}/summary.txt",
        },
        {"id": "toolu_u3", "tool": "TaskUpdate", "arg": "2", "result": "Updated task #2 status"},
    ]
    assert explore == {
        "id": AGENT_ID,
        "name": "Explore",
        "description": "Read CLAUDE.md file",
        "status": "done",
        "activity": None,
        "started_at": at(13),
        "finished_at": at(17),
        "steps": [
            {"id": "toolu_read", "tool": "Read", "arg": "CLAUDE.md", "result": "1 Demo repo."}
        ],
    }
    assert feed.tracker.summary == "Done. Both tasks completed."


def test_changes_report_what_moved() -> None:
    feed = Feed()
    create_use, create_result = create_task(1, "One", "Doing one")

    assert feed.apply("session.created", {"session": {"cwd": ROOT}}) == (False, Change.NONE)
    assert feed.state("running") == (False, Change.NONE)
    assert feed.apply("session.message", create_use) == (False, Change.ACTIVITY)
    assert feed.apply("session.message", create_result) == (True, Change.ACTIVITY)
    assert feed.apply("session.message", start_agent_message("a1")) == (False, Change.LIFECYCLE)
    assert feed.apply("session.message", message(text("hi"))) == (False, Change.NONE)
    assert feed.apply("session.usage", {}) == (False, Change.NONE)
    assert feed.state("waiting") == (False, Change.NONE)
    assert feed.state("idle") == (False, Change.LIFECYCLE)
    assert feed.agent("main")["activity"] is None


def test_in_place_sessions_shorten_paths_against_their_checkout() -> None:
    feed = Feed()
    feed.apply("session.created", {"session": {"cwd": "/src/app"}})

    feed.messages(message(tool_use("e1", "Edit", {"file_path": "/src/app/src/x.ts"})))

    assert feed.agent("main")["activity"] == "Edit src/x.ts"


def test_tasks_tolerate_errors_unknown_ids_odd_input_and_out_of_order_results() -> None:
    feed = Feed()
    second_use, second_result = create_task(2, "Second", "Doing two")
    first_use, first_result = create_task(1, "First", "Doing one")
    feed.messages(
        second_use,
        first_use,
        # Parallel calls whose results come back in the other order.
        first_result,
        second_result,
        message(tool_use("bad", "TaskCreate", {"subject": "Broken"})),
        message(tool_result("bad", "failed to create", is_error=True)),
        message(tool_use("odd", "TaskCreate", {"subject": 7, "extra": True})),
        message(tool_result("odd", "Task #3 created successfully: Odd one")),
        message(tool_use("nope", "TaskCreate", {"subject": "No id"})),
        message(tool_result("nope", "something unexpected")),
        *update_task("u_unknown", "9", "completed"),
        *update_task("u_status", "1", "exploding"),
        message(
            tool_use(
                "u_fields",
                "TaskUpdate",
                {"taskId": 2, "status": "deleted", "subject": "Renamed", "activeForm": 5},
            )
        ),
        message(tool_result("u_fields", "Updated task #2")),
        message(tool_use("u_failed", "TaskUpdate", {"taskId": "1", "status": "completed"})),
        message(tool_result("u_failed", "no such task", is_error=True)),
        message(tool_result("never_called", "orphan result")),
    )

    assert feed.tasks() == [
        {
            "id": "1",
            "subject": "First",
            "description": "About First",
            "active_form": "Doing one",
            "status": "pending",
        },
        {
            "id": "2",
            "subject": "Renamed",
            "description": "About Second",
            "active_form": "Doing two",
            "status": "deleted",
        },
        {
            "id": "3",
            "subject": "Odd one",
            "description": None,
            "active_form": None,
            "status": "pending",
        },
    ]


def test_only_the_main_agent_task_list_counts() -> None:
    feed = Feed()
    feed.messages(start_agent_message("a1"))
    use, result = create_task(1, "Sub task", "Working")

    feed.messages({**use, "parent_tool_use_id": "a1"}, {**result, "parent_tool_use_id": "a1"})

    assert feed.tasks() == []
    assert feed.agent("a1")["activity"] == "TaskCreate Sub task"


def test_subagents_nest_fail_and_keep_their_last_steps() -> None:
    feed = Feed()
    feed.state("running")
    feed.messages(
        start_agent_message("outer", description="Plan it", subagent_type="Plan"),
        start_agent_message("inner", parent="outer"),
        message(tool_use("g1", "Grep", {"pattern": "TODO"}), parent="inner"),
        message(text("ignored"), parent="unknown-parent"),
        message(tool_result("inner", "inner crashed", is_error=True), parent="outer"),
        start_agent_message("plain", subagent_type=3, description=None),
    )
    for n in range(MAX_STEPS + 2):
        feed.messages(message(tool_use(f"b{n}", "Bash", {"command": f"echo {n}"}), parent="outer"))
    feed.messages(message(tool_result("b0", "scrolled away"), parent="outer"))

    outer = feed.agent("outer")
    inner = feed.agent("inner")
    plain = feed.agent("plain")
    assert (outer["name"], outer["description"], outer["status"]) == ("Plan", "Plan it", "running")
    assert outer["activity"] == f"Bash echo {MAX_STEPS + 1}"
    assert len(outer["steps"]) == MAX_STEPS  # pyright: ignore[reportArgumentType]
    assert outer["steps"][-1]["arg"] == f"echo {MAX_STEPS + 1}"  # pyright: ignore[reportIndexIssue, reportOptionalSubscript, reportCallIssue, reportArgumentType]
    assert (inner["status"], inner["finished_at"], inner["activity"]) == ("failed", at(6), None)
    assert inner["steps"] == [{"id": "g1", "tool": "Grep", "arg": "TODO", "result": None}]
    assert (plain["name"], plain["description"]) == ("agent", None)


@pytest.mark.parametrize(
    ("state", "status"), [("interrupted", "done"), ("failed", "failed"), ("closed", "done")]
)
def test_a_cut_off_turn_fails_its_running_subagents(state: str, status: str) -> None:
    feed = Feed()
    feed.state("running")
    feed.messages(start_agent_message("a1"))

    assert feed.state(state) == (False, Change.LIFECYCLE)

    assert feed.agent("main")["status"] == status
    assert feed.agent("a1")["status"] == "failed"
    assert feed.agent("a1")["finished_at"] == at(3)


def test_a_finished_subagent_stays_done_and_main_runs_again() -> None:
    feed = Feed()
    feed.state("running")
    feed.messages(start_agent_message("a1"), message(tool_result("a1", "report")))
    feed.state("idle")

    assert feed.state("running") == (False, Change.LIFECYCLE)
    assert feed.state("failed") == (False, Change.LIFECYCLE)

    assert feed.agent("main")["finished_at"] == at(6)
    assert feed.agent("a1")["status"] == "done"


@pytest.mark.parametrize(
    ("tool_input", "arg"),
    [
        ({"command": "pytest -q\nmore"}, "pytest -q"),
        ({"file_path": f"{ROOT}/src/x.ts"}, "src/x.ts"),
        ({"file_path": "/elsewhere/y.py"}, "/elsewhere/y.py"),
        ({"notebook_path": "nb.ipynb"}, "nb.ipynb"),
        ({"pattern": "TODO", "path": "src"}, "TODO"),
        ({"url": "https://example.com"}, "https://example.com"),
        ({"taskId": 4}, "4"),
        ({"other": "x"}, ""),
        ({"command": ""}, ""),
        ({"command": "x" * 200}, "x" * 79 + "…"),
    ],
)
def test_short_args(tool_input: dict[str, JsonValue], arg: str) -> None:
    assert short_arg(tool_input, ROOT) == arg


def test_short_args_without_a_root_keep_paths() -> None:
    assert short_arg({"file_path": f"{ROOT}/a.py"}, None) == f"{ROOT}/a.py"


@pytest.mark.parametrize(
    ("content", "is_error", "result"),
    [
        ("\n\n  first   line \nsecond", False, "first line"),
        ("", False, ""),
        ("boom", True, "error: boom"),
    ],
)
def test_short_results(content: str, is_error: bool, result: str) -> None:
    assert short_result(content, is_error) == result
