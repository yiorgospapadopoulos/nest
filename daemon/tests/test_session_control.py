import asyncio
from collections.abc import AsyncIterator, Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from harness.approvals.models import Approval, ApprovalKind, ApprovalStatus
from harness.config.models import WorktreeConfig
from harness.events import types
from harness.providers.base import (
    PermissionDecision,
    Question,
    QuestionAnswer,
    QuestionOption,
    QuestionRequest,
)
from harness.sessions.errors import (
    NoTurnInProgressError,
    SessionClosedError,
    SessionNotFoundError,
)
from harness.sessions.models import SessionState, UpdateSession
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import (
    ask,
    ask_together,
    background,
    commit,
    crash,
    hang,
    question,
    reply,
    switched,
    until_interrupted,
)
from tests.fakes import FakeClock
from tests.git_support import git
from tests.session_support import Env
from tests.test_session_store import new_session


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def pending_items(env: Env, session_id: str, count: int = 1) -> list[Approval]:
    async def created() -> bool:
        return len(await env.approvals.list_approvals(ApprovalStatus.PENDING)) == count

    await until(created)
    items = await env.approvals.list_approvals(ApprovalStatus.PENDING)
    assert {item.session_id for item in items} == {session_id}
    return items


async def test_permission_prompt_waits_for_the_queue(env: Env) -> None:
    env.provider.script(ask("Bash", reply("ran it")))
    created = await env.create()
    await env.reach(created.id, SessionState.WAITING)
    (item,) = await pending_items(env, created.id)

    await env.approvals.resolve(item.id, {"behavior": "allow"})
    await env.reach(created.id, SessionState.IDLE)

    assert item.kind is ApprovalKind.PERMISSION
    assert item.payload == {
        "tool": "Bash",
        "input": {"x": 1},
        "title": None,
        "reason": None,
        "always_rule": None,
    }
    assert env.provider.runs[0].decisions == [PermissionDecision("allow")]
    assert await env.states(created.id) == ["starting", "running", "waiting", "running", "idle"]
    # The hooks follow every change after the initial state.
    assert env.hooks.states == [
        (created.id, state)
        for state in (
            SessionState.RUNNING,
            SessionState.WAITING,
            SessionState.RUNNING,
            SessionState.IDLE,
        )
    ]


async def test_questions_wait_for_answers_from_the_queue(env: Env) -> None:
    request = QuestionRequest((Question("Which?", None, (QuestionOption("A"),), False),))
    env.provider.script(question(request, reply("thanks")))
    created = await env.create()
    await env.reach(created.id, SessionState.WAITING)
    (item,) = await pending_items(env, created.id)

    await env.approvals.resolve(item.id, {"answers": {"Which?": "A"}})
    await env.reach(created.id, SessionState.IDLE)

    assert item.kind is ApprovalKind.QUESTION
    assert env.provider.runs[0].answers == [QuestionAnswer({"Which?": "A"})]


async def test_parallel_prompts_keep_the_session_waiting_until_all_are_answered(env: Env) -> None:
    env.provider.script(ask_together("Read", "Edit", then=reply("both done")))
    created = await env.create()
    first, second = await pending_items(env, created.id, 2)
    await env.reach(created.id, SessionState.WAITING)

    await env.approvals.resolve(first.id, {"behavior": "allow"})

    async def first_resolved() -> bool:
        return types.APPROVAL_RESOLVED in await env.event_types(created.id)

    await until(first_resolved)
    still_waiting = (await env.store.get(created.id)).state
    await env.approvals.resolve(second.id, {"behavior": "deny"})
    await env.reach(created.id, SessionState.IDLE)

    assert still_waiting is SessionState.WAITING
    assert await env.states(created.id) == ["starting", "running", "waiting", "running", "idle"]


async def test_interrupt_stops_the_turn_and_denies_pending_prompts(env: Env) -> None:
    env.provider.script(ask("Bash", until_interrupted()), reply("resumed"))
    created = await env.create()
    await env.reach(created.id, SessionState.WAITING)

    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)

    (run,) = env.provider.runs
    assert run.decisions == [PermissionDecision("deny", "interrupted by the user")]
    assert run.calls == [("interrupt", None)]
    await env.manager.send(created.id, "carry on", [])
    await env.reach(created.id, SessionState.IDLE)
    assert len(env.provider.runs) == 1


async def test_interrupt_before_the_agent_runs_cancels_the_start(env: Env) -> None:
    env.provider.open_gate = asyncio.Event()
    created = await env.create()
    await env.reach(created.id, SessionState.RUNNING)

    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)

    assert env.provider.runs == []


async def test_interrupt_needs_a_turn_in_progress(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    with pytest.raises(NoTurnInProgressError, match="no turn in progress"):
        await env.manager.interrupt(created.id)
    with pytest.raises(SessionNotFoundError):
        await env.manager.interrupt("nope")


async def test_update_persists_and_applies_to_a_live_run(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    updated = await env.manager.update(
        created.id, UpdateSession(model="claude-opus-5", permission_mode="plan")
    )
    unchanged = await env.manager.update(created.id, UpdateSession())

    assert (updated.model, updated.permission_mode) == ("claude-opus-5", "plan")
    assert (unchanged.model, unchanged.permission_mode) == ("claude-opus-5", "plan")
    assert env.provider.runs[0].calls == [
        ("set_model", "claude-opus-5"),
        ("set_permission_mode", "plan"),
    ]


async def test_a_mode_the_engine_switched_to_is_saved_and_announced(env: Env) -> None:
    """BUG-43: the clients and the next control change follow the engine's own switch."""
    env.provider.script(switched("plan", reply("Planning now.")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    switched_to = await env.store.get(created.id)
    back = await env.manager.update(created.id, UpdateSession(permission_mode="acceptEdits"))

    assert switched_to.permission_mode == "plan"
    updates = [
        e.payload["changes"]
        for e in await env.bus.session_events(created.id)
        if e.type == types.SESSION_UPDATED
    ]
    assert updates == [{"permission_mode": "plan"}, {"permission_mode": "acceptEdits"}]
    assert back.permission_mode == "acceptEdits"
    assert env.provider.runs[0].calls == [("set_permission_mode", "acceptEdits")]


async def test_a_new_effort_reopens_the_run_at_the_next_message(env: Env) -> None:
    """The engine takes effort only when a run opens (I-006)."""
    env.provider.script(reply("one"), reply("two"), reply("three"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    updated = await env.manager.update(created.id, UpdateSession(effort="high"))

    assert updated.effort == "high"
    assert env.provider.runs[0].closed is False
    assert env.provider.runs[0].calls == []
    await env.manager.send(created.id, "think harder", [])
    await until_results(env, created.id, 2)
    assert env.provider.runs[0].closed is True
    assert env.provider.runs[1].spec.effort == "high"
    assert env.provider.runs[1].spec.resume_id == "sdk-1"
    await env.manager.send(created.id, "again", [])
    await until_results(env, created.id, 3)
    assert len(env.provider.runs) == 2


async def test_switching_to_bypass_reopens_the_run_in_bypass(env: Env) -> None:
    """Claude Code refuses a live switch into bypass unless launched with a flag that offers
    it to every run (D046); harness reopens the run in bypass at the next message instead."""
    env.provider.script(reply("one"), reply("two"), reply("three"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    updated = await env.manager.update(
        created.id, UpdateSession(permission_mode="bypassPermissions")
    )

    assert updated.permission_mode == "bypassPermissions"
    assert env.provider.runs[0].calls == []
    await env.manager.send(created.id, "go on", [])
    await until_results(env, created.id, 2)
    assert env.provider.runs[0].closed is True
    assert env.provider.runs[1].spec.permission_mode == "bypassPermissions"
    assert env.provider.runs[1].spec.resume_id == "sdk-1"
    # A run opened in bypass can leave it and come back live.
    await env.manager.update(created.id, UpdateSession(permission_mode="default"))
    await env.manager.update(created.id, UpdateSession(permission_mode="bypassPermissions"))
    assert env.provider.runs[1].calls == [
        ("set_permission_mode", "default"),
        ("set_permission_mode", "bypassPermissions"),
    ]
    await env.manager.send(created.id, "again", [])
    await until_results(env, created.id, 3)
    assert len(env.provider.runs) == 2


async def test_bypass_waits_while_background_tasks_run(env: Env) -> None:
    env.provider.script(background(1, reply("started")), reply("two"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.update(created.id, UpdateSession(permission_mode="bypassPermissions"))
    await env.manager.send(created.id, "how is it going?", [])
    await until_results(env, created.id, 2)

    assert len(env.provider.runs) == 1
    assert env.provider.runs[0].calls == []


async def test_a_new_effort_waits_while_background_tasks_run(env: Env) -> None:
    """Reopening would stop the agent's background work; the effort applies at a later open."""
    env.provider.script(background(1, reply("started")), reply("two"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.update(created.id, UpdateSession(effort="low"))
    await env.manager.send(created.id, "how is it going?", [])
    await until_results(env, created.id, 2)

    assert len(env.provider.runs) == 1
    assert env.provider.runs[0].closed is False


async def test_update_without_a_live_run_only_persists(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.shutdown()
    manager = env.build(timedelta(hours=1))

    updated = await manager.update(created.id, UpdateSession(permission_mode="default"))

    assert updated.permission_mode == "default"
    assert env.provider.runs[0].calls == []


async def test_close_removes_the_worktree_and_branch(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    session = await env.reach(created.id, SessionState.IDLE)
    assert session.worktree_path is not None

    closed = await env.manager.close(created.id, remove_worktree=True)

    assert closed.state is SessionState.CLOSED
    assert not session.worktree_path.exists()
    assert str(session.branch) not in git(env.repo_path, "branch")
    assert env.provider.runs[0].closed is True
    with pytest.raises(SessionClosedError):
        await env.manager.close(created.id, remove_worktree=False)
    with pytest.raises(SessionClosedError):
        await env.manager.update(created.id, UpdateSession(model="x"))
    with pytest.raises(SessionClosedError):
        await env.manager.update(created.id, UpdateSession(effort="high"))


async def test_close_keeps_the_worktree_by_default_and_stops_a_running_turn(env: Env) -> None:
    env.provider.script(ask("Bash", hang()))
    created = await env.create()
    session = await env.reach(created.id, SessionState.WAITING)

    closed = await env.manager.close(created.id, remove_worktree=False)

    assert closed.state is SessionState.CLOSED
    assert session.worktree_path is not None
    assert session.worktree_path.exists()
    assert env.provider.runs[0].closed is True
    (item,) = await env.approvals.list_approvals()
    assert item.status is ApprovalStatus.EXPIRED
    assert item.resolution == {"reason": "the session was closed"}
    assert (await env.states(created.id))[-1] == "closed"


async def test_closing_an_in_place_session_never_removes_the_checkout(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.close(created.id, remove_worktree=True)

    assert env.repo_path.is_dir()


async def test_closing_a_session_without_a_live_run(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.shutdown()
    manager = env.build(timedelta(hours=1))

    closed = await manager.close(created.id, remove_worktree=False)

    assert closed.state is SessionState.CLOSED


async def test_idle_runs_are_closed_and_resumed_lazily(env: Env) -> None:
    manager = env.build(timedelta(milliseconds=10))
    env.manager = manager
    env.provider.script(reply("one"), reply("two"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    first = env.provider.runs[0]
    await until(lambda: first.closed)

    await manager.send(created.id, "more", [])
    await until(lambda: len(env.provider.runs) == 2 and env.provider.runs[1].closed)

    assert env.provider.runs[1].spec.resume_id == "sdk-1"


async def test_a_new_turn_cancels_the_idle_close(env: Env) -> None:
    env.provider.script(reply("one"), reply("two"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.send(created.id, "more", [])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)

    assert len(env.provider.runs) == 1
    assert env.provider.runs[0].closed is False


async def test_errors_while_closing_a_run_are_ignored(env: Env) -> None:
    env.provider.script(reply("ok"))
    env.provider.close_error = RuntimeError("already gone")
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    closed = await env.manager.close(created.id, remove_worktree=False)

    assert closed.state is SessionState.CLOSED


async def test_ref_changes_during_a_turn_are_flagged(env: Env) -> None:
    env.provider.script(reply("clean"), commit(reply("committed anyway")))
    created = await env.create()
    clean = await env.reach(created.id, SessionState.IDLE)

    await env.manager.send(created.id, "commit it", [])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)
    flagged = await env.reach(created.id, SessionState.IDLE)

    assert clean.git_violation is False
    assert flagged.git_violation is True
    violation = next(
        e for e in await env.bus.session_events(created.id) if e.type == types.SESSION_GIT_VIOLATION
    )
    refs = [change["ref"] for change in violation.payload["changes"]]  # type: ignore[index, union-attr]
    assert refs == ["HEAD", f"refs/heads/{flagged.branch}"]


async def test_recover_marks_in_flight_sessions_interrupted(env: Env) -> None:
    # Rows left behind by a previous daemon process.
    rows: dict[SessionState, str] = {}
    for state in (SessionState.RUNNING, SessionState.WAITING, SessionState.IDLE):
        session = await env.store.create(new_session())
        rows[state] = (await env.store.update(session.id, state=state)).id

    await env.manager.recover()

    for state, session_id in rows.items():
        expected = SessionState.IDLE if state is SessionState.IDLE else SessionState.INTERRUPTED
        assert (await env.store.get(session_id)).state is expected
    assert await env.states(rows[SessionState.RUNNING]) == ["interrupted"]
    assert await env.states(rows[SessionState.IDLE]) == []


async def test_shutdown_interrupts_turns_and_closes_runs(env: Env) -> None:
    env.provider.script(hang())
    created = await env.create()
    await env.reach(created.id, SessionState.RUNNING)
    await until(lambda: bool(env.provider.runs) and bool(env.provider.runs[0].inputs))

    await env.manager.shutdown()

    assert (await env.store.get(created.id)).state is SessionState.INTERRUPTED
    assert env.provider.runs[0].closed is True


async def test_one_sessions_failure_does_not_stop_shutdown_of_the_others(
    env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """IMP-13 (I-M): every agent is stopped, and a failure is logged, not raised."""
    env.provider.script(hang(), hang())
    first = await env.create()
    second = await env.create()
    await until(lambda: len(env.provider.runs) == 2 and all(r.inputs for r in env.provider.runs))
    expire = env.approvals.expire

    async def failing(session_id: str, kinds: Sequence[ApprovalKind], reason: str) -> None:
        if session_id == first.id:
            raise RuntimeError("database is locked")
        await expire(session_id, kinds, reason)

    monkeypatch.setattr(env.approvals, "expire", failing)

    await env.manager.shutdown()

    assert (await env.store.get(second.id)).state is SessionState.INTERRUPTED
    assert [run.closed for run in env.provider.runs].count(True) == 1
    assert f"stopping session {first.id} failed" in caplog.text
    assert "database is locked" in caplog.text


async def test_setup_in_progress_is_interrupted(env: Env) -> None:
    env.repos.update_worktree_config("repo", WorktreeConfig(setup=["sleep 30"]))
    created = await env.create()
    await until(lambda: (env.paths.logs_dir / f"setup-{created.id}.log").exists())

    await env.manager.interrupt(created.id)

    await env.reach(created.id, SessionState.INTERRUPTED)


async def test_turns_the_agent_starts_on_its_own_do_not_steal_the_next_answer(env: Env) -> None:
    env.provider.script(reply("started a background sleep"), reply("your actual answer"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    run = env.provider.runs[0]

    run.emit(reply("the sleep finished"))
    await until_results(env, created.id, 2)
    await env.manager.send(created.id, "what is 2 + 2?", [])
    await until_results(env, created.id, 3)

    events = await env.bus.session_events(created.id)
    flow = [
        e.payload.get("text") or e.payload.get("state") or e.type
        for e in events
        if e.type in (types.SESSION_USER_MESSAGE, types.SESSION_STATE, types.SESSION_RESULT)
    ]
    assert flow == [
        "starting",
        "Fix the bug\nDetails here",
        "running",
        types.SESSION_RESULT,
        "idle",
        "running",
        types.SESSION_RESULT,
        "idle",
        "what is 2 + 2?",
        "running",
        types.SESSION_RESULT,
        "idle",
    ]
    last = [e for e in events if e.type == types.SESSION_MESSAGE][-1]
    assert last.payload["blocks"] == [{"type": "text", "text": "your actual answer"}]


async def until_results(env: Env, session_id: str, count: int) -> None:
    async def done() -> bool:
        events = await env.bus.session_events(session_id)
        states = [e.payload["state"] for e in events if e.type == types.SESSION_STATE]
        results = [e for e in events if e.type == types.SESSION_RESULT]
        return len(results) == count and states[-1] == "idle"

    await until(done)


async def test_a_message_is_queued_while_the_agent_works_on_its_own(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    env.provider.runs[0].emit(hang())
    await env.reach(created.id, SessionState.RUNNING)

    sent = await env.manager.send(created.id, "hello?", [])
    await env.manager.interrupt(created.id)
    assert sent.queued_message is not None
    assert [m.text for m in await env.manager.queued(created.id)] == ["hello?"]
    assert env.provider.runs[0].calls == [("interrupt", None)]


async def test_agent_initiated_ref_changes_are_flagged(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    env.provider.runs[0].emit(commit(reply("committed later")))
    await until_results(env, created.id, 2)

    assert (await env.store.get(created.id)).git_violation is True


async def test_idle_close_waits_for_background_tasks(env: Env) -> None:
    env.manager = env.build(timedelta(milliseconds=10))
    env.provider.script(background(1, reply("started")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    run = env.provider.runs[0]

    await asyncio.sleep(0.05)
    assert run.closed is False
    run.emit(background(0))
    await until(lambda: run.closed)


async def test_a_crash_while_idle_drops_the_run_and_the_next_message_resumes(env: Env) -> None:
    env.provider.script(reply("ok"), reply("back"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    env.provider.runs[0].emit(crash("gone"))
    await until(lambda: env.provider.runs[0].closed)
    await env.manager.send(created.id, "still there?", [])
    await until_results(env, created.id, 2)

    assert (await env.store.get(created.id)).state is SessionState.IDLE
    assert env.provider.runs[1].spec.resume_id == "sdk-1"
    assert "failed" not in await env.states(created.id)


async def test_shutdown_while_waiting_for_permission_interrupts(env: Env) -> None:
    env.provider.script(ask("Bash", reply("never")))
    created = await env.create()
    await env.reach(created.id, SessionState.WAITING)

    await env.manager.shutdown()

    assert (await env.store.get(created.id)).state is SessionState.INTERRUPTED
    assert env.provider.runs[0].closed is True


async def test_close_waits_for_the_agent_to_exit_before_removing_the_worktree(env: Env) -> None:
    env.provider.exit_hook = True
    env.provider.script(reply("ok"))
    created = await env.create()
    session = await env.reach(created.id, SessionState.IDLE)
    assert session.worktree_path is not None

    await env.manager.close(created.id, remove_worktree=True)

    assert not session.worktree_path.exists()
    assert str(session.worktree_path) not in git(env.repo_path, "worktree", "list")
