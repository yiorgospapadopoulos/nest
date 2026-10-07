"""Background subagents and commands: they outlive their tool call and the main turn."""

from pydantic import JsonValue

from harness.tracking.agents import Change
from tests.test_tracking import Feed, at
from tests.tracking_fixture import message, start_agent_message, text, tool_result, tool_use


def task(feed: Feed, task_id: str, phase: str, **fields: JsonValue) -> tuple[bool, Change]:
    return feed.apply("session.agent_task", {"task_id": task_id, "phase": phase, **fields})


def background(feed: Feed) -> dict[str, JsonValue]:
    return feed.tracker.agents.background().model_dump(mode="json")


def statuses(feed: Feed) -> list[tuple[JsonValue, JsonValue]]:
    items = background(feed)["items"]
    assert isinstance(items, list)
    return [(item["id"], item["status"]) for item in items]  # pyright: ignore[reportIndexIssue, reportOptionalSubscript, reportCallIssue, reportArgumentType]


def test_a_background_subagent_runs_on_after_its_call_and_the_turn_end() -> None:
    feed = Feed()
    feed.state("running")
    feed.messages(start_agent_message("a1", run_in_background=True))
    task(feed, "t1", "started", tool_use_id="a1", task_type="local_agent", background=True)
    feed.messages(message(tool_result("a1", "Async agent launched")), message(text("Started.")))

    assert feed.state("idle") == (False, Change.LIFECYCLE)

    assert feed.agent("main")["status"] == "done"
    assert (feed.agent("a1")["status"], feed.agent("a1")["finished_at"]) == ("running", None)
    assert feed.agent("a1")["steps"] == []
    assert background(feed) == {
        "running": 1,
        "completed": 0,
        "items": [
            {
                "id": "a1",
                "kind": "agent",
                "name": "Explore",
                "description": "Look around",
                "status": "running",
                "started_at": at(2),
                "finished_at": None,
            }
        ],
    }

    assert task(feed, "t1", "finished", tool_use_id="a1", status="completed") == (
        False,
        Change.LIFECYCLE,
    )
    assert (feed.agent("a1")["status"], feed.agent("a1")["finished_at"]) == ("done", at(7))
    assert (background(feed)["running"], background(feed)["completed"]) == (0, 1)
    # A repeated notice changes nothing.
    assert task(feed, "t1", "finished", tool_use_id="a1", status="completed") == (
        False,
        Change.NONE,
    )


def test_failed_and_stopped_tasks_fail_their_subagent() -> None:
    feed = Feed()
    feed.messages(
        start_agent_message("a1", run_in_background=True),
        start_agent_message("a2", run_in_background=True),
        start_agent_message("a3", run_in_background=True),
        message(tool_result("a3", "could not start", is_error=True)),
    )
    task(feed, "t1", "started", tool_use_id="a1", background=True)
    task(feed, "t2", "started", tool_use_id="a2", background=True)

    task(feed, "t1", "finished", status="failed")
    task(feed, "t2", "finished", tool_use_id="a2", status="stopped")

    assert statuses(feed) == [("a1", "failed"), ("a2", "failed"), ("a3", "failed")]


def test_the_task_start_alone_marks_a_subagent_as_background() -> None:
    feed = Feed()
    feed.messages(start_agent_message("a1"))
    assert task(feed, "t1", "started", tool_use_id="a1", background=True) == (
        False,
        Change.LIFECYCLE,
    )
    feed.messages(message(tool_result("a1", "Async agent launched")))

    assert feed.agent("a1")["status"] == "running"


def test_a_subagent_moved_to_the_background_runs_on_whatever_comes_first() -> None:
    feed = Feed()
    feed.messages(start_agent_message("a1"), start_agent_message("a2"))
    task(feed, "t1", "started", tool_use_id="a1", background=False)
    task(feed, "t2", "started", tool_use_id="a2", background=False)

    task(feed, "t1", "backgrounded")
    feed.messages(message(tool_result("a1", "moved to the background")))
    feed.messages(message(tool_result("a2", "moved to the background")))
    assert feed.agent("a2")["status"] == "done"
    assert task(feed, "t2", "backgrounded") == (False, Change.LIFECYCLE)
    assert task(feed, "t2", "backgrounded") == (False, Change.NONE)

    assert statuses(feed) == [("a1", "running"), ("a2", "running")]
    assert feed.agent("a2")["finished_at"] is None
    task(feed, "t2", "finished", status="completed")
    assert statuses(feed) == [("a1", "running"), ("a2", "done")]


def test_foreground_subagents_still_end_with_their_call() -> None:
    feed = Feed()
    feed.messages(start_agent_message("a1"))
    task(feed, "t1", "started", tool_use_id="a1", task_type="local_agent", background=False)

    assert task(feed, "t1", "finished", tool_use_id="a1", status="completed") == (
        False,
        Change.NONE,
    )
    assert feed.agent("a1")["status"] == "running"
    feed.messages(message(tool_result("a1", "report")))
    assert feed.agent("a1")["status"] == "done"
    assert background(feed)["completed"] == 1


def test_background_commands_are_followed_until_their_task_ends() -> None:
    feed = Feed()
    feed.state("running")
    run = {"command": "npm run dev\n--port 3000", "description": "Start the dev server"}
    assert feed.apply(
        "session.message", message(tool_use("b1", "Bash", {**run, "run_in_background": True}))
    ) == (False, Change.LIFECYCLE)
    task(feed, "t1", "started", tool_use_id="b1", task_type="local_bash", background=True)
    feed.messages(message(tool_result("b1", "Command running in background with ID: t1")))
    feed.state("idle")

    assert [a["id"] for a in feed.agents()] == ["main"]
    assert background(feed) == {
        "running": 1,
        "completed": 0,
        "items": [
            {
                "id": "b1",
                "kind": "bash",
                "name": "npm run dev",
                "description": "Start the dev server",
                "status": "running",
                "started_at": at(2),
                "finished_at": None,
            }
        ],
    }

    task(feed, "t1", "finished", status="completed")
    assert statuses(feed) == [("b1", "done")]


def test_a_command_that_cannot_start_fails() -> None:
    feed = Feed()
    feed.messages(
        message(tool_use("b1", "Bash", {"command": "nope", "run_in_background": True})),
        message(tool_result("b1", "not allowed", is_error=True)),
        message(tool_use("b2", "Bash", {"run_in_background": True})),
    )

    assert statuses(feed) == [("b1", "failed"), ("b2", "running")]
    assert background(feed)["items"][1]["name"] == "command"  # pyright: ignore[reportIndexIssue, reportOptionalSubscript, reportCallIssue, reportArgumentType]


def test_a_command_moved_to_the_background_keeps_its_command() -> None:
    feed = Feed()
    feed.messages(message(tool_use("b1", "Bash", {"command": "make test", "description": "Test"})))
    feed.messages(message(tool_use("b2", "Bash", {"command": "pytest"})))
    feed.messages(message(tool_result("b2", "1 passed")))
    task(feed, "t1", "started", tool_use_id="b1", task_type="local_bash", background=False)
    task(feed, "t3", "started", task_type="local_bash", description="sleep 40", background=True)

    assert task(feed, "t1", "backgrounded") == (False, Change.LIFECYCLE)
    feed.messages(message(tool_result("b1", "moved to the background")))

    items = background(feed)["items"]
    assert isinstance(items, list)
    assert [(i["id"], i["name"], i["description"], i["status"]) for i in items] == [  # pyright: ignore[reportIndexIssue, reportOptionalSubscript, reportCallIssue, reportArgumentType]
        ("t3", "sleep 40", None, "running"),
        ("b1", "make test", "Test", "running"),
    ]


def test_unknown_or_other_tasks_change_nothing() -> None:
    feed = Feed()
    feed.messages(message(tool_use("b1", "Bash", {"command": "ls", "run_in_background": True})))

    assert task(feed, "t1", "backgrounded") == (False, Change.NONE)
    assert task(feed, "t2", "started", task_type="local_workflow", background=True) == (
        False,
        Change.NONE,
    )
    assert task(
        feed, "t3", "started", tool_use_id="b1", task_type="local_bash", background=True
    ) == (
        False,
        Change.NONE,
    )
    assert task(feed, "t9", "finished", status="completed") == (False, Change.NONE)
    assert statuses(feed) == [("b1", "running")]


def test_a_cut_off_turn_fails_background_work_and_a_late_notice_corrects_it() -> None:
    feed = Feed()
    feed.state("running")
    feed.messages(
        start_agent_message("a1", run_in_background=True),
        message(tool_use("b1", "Bash", {"command": "sleep 9", "run_in_background": True})),
    )
    task(feed, "t1", "started", tool_use_id="a1", background=True)

    feed.state("interrupted")
    assert statuses(feed) == [("a1", "failed"), ("b1", "failed")]

    task(feed, "t1", "finished", status="completed")
    assert statuses(feed) == [("a1", "done"), ("b1", "failed")]
