"""Moments where two things happen to a session at once (B31: BUG-02, BUG-12 to BUG-19)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.attachments.store import Attachment
from nestd.config.models import PermissionMode, RepoConfig
from nestd.errors import ConflictError
from nestd.events import types
from nestd.providers.base import UserInput
from nestd.sessions.errors import SessionBusyError, SessionClosedError
from nestd.sessions.live import LiveSession
from nestd.sessions.models import QueuedMessage, Session, SessionState, UpdateSession
from nestd.storage.db import Database
from nestd.worktrees.manager import Worktree
from tests.async_support import until
from tests.fake_provider import FakeRun, background, hang, reply, until_interrupted
from tests.fakes import FakeClock
from tests.session_support import Env, gate_worktree_add


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def user_messages(env: Env, session_id: str) -> list[object]:
    return [
        event.payload["text"]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_USER_MESSAGE
    ]


def texts(run: FakeRun) -> list[str]:
    return [user_input.text for user_input in run.inputs]


async def test_stop_as_a_queued_message_starts_keeps_it_from_the_agent(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-12: Stop pressed while the next queued message is on its way to the agent."""
    release_first = asyncio.Event()

    async def first_turn(run: FakeRun) -> None:
        await release_first.wait()
        await reply("first done")(run)

    env.provider.script(reply("prompt done"), first_turn, reply("second done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "message A", [])
    await env.reach(created.id, SessionState.RUNNING)
    await env.manager.send(created.id, "message B", [])
    in_gap, leave_gap = asyncio.Event(), asyncio.Event()
    original = env.attachments.for_session

    async def slow_for_session(ids: list[str], session_id: str | None) -> list[Attachment]:
        in_gap.set()
        await leave_gap.wait()
        return await original(ids, session_id)

    monkeypatch.setattr(env.attachments, "for_session", slow_for_session)
    release_first.set()
    await asyncio.wait_for(in_gap.wait(), 5)

    await env.manager.interrupt(created.id)
    leave_gap.set()
    await env.reach(created.id, SessionState.INTERRUPTED)

    (run,) = env.provider.runs
    assert texts(run) == ["Fix the bug\nDetails here", "message A"]
    assert ("interrupt", None) not in run.calls
    # Shown like a message sent just before Stop, so it is not lost.
    assert await user_messages(env, created.id) == [
        "Fix the bug\nDetails here",
        "message A",
        "message B",
    ]
    assert await env.manager.queued(created.id) == []
    assert not env.manager.busy(created.id)


async def test_a_nudge_while_the_run_opens_starts_the_next_turn(env: Env) -> None:
    """BUG-13, BUG-58: the nudge interrupts the start, whose prompt the agent never got;
    the prompt then goes first, shown once, and the nudge right after it (D036).
    """
    gate = asyncio.Event()
    env.provider.open_gate = gate
    env.provider.script(reply("on it"), reply("answer to the nudge"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.RUNNING)

    result = await env.manager.send(created.id, "You seem stuck", [], interrupt=True)
    env.provider.open_gate = None
    gate.set()
    await until(lambda: bool(env.provider.runs) and len(env.provider.runs[0].inputs) == 2)
    await env.reach(created.id, SessionState.IDLE)

    assert result.queued_message is not None
    (run,) = env.provider.runs
    assert texts(run) == ["Fix the bug\nDetails here", "You seem stuck"]
    assert await user_messages(env, created.id) == ["Fix the bug\nDetails here", "You seem stuck"]
    assert await env.manager.queued(created.id) == []
    assert (await env.states(created.id))[-1] == "idle"
    assert "interrupted" not in await env.states(created.id)


async def test_a_nudge_while_the_worktree_is_created_keeps_the_prompt(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-58: cut off before it was shown, the prompt is shown when it goes to the agent."""
    started, release = gate_worktree_add(monkeypatch)
    env.provider.script(reply("on it"), reply("answer to the nudge"))
    created = await env.create()
    await asyncio.wait_for(started.wait(), 5)

    await env.manager.send(created.id, "You seem stuck", [], interrupt=True)
    release.set()
    await until(lambda: bool(env.provider.runs) and len(env.provider.runs[0].inputs) == 2)
    session = await env.reach(created.id, SessionState.IDLE)

    (run,) = env.provider.runs
    assert run.spec.cwd == session.worktree_path
    assert texts(run) == ["Fix the bug\nDetails here", "You seem stuck"]
    assert await user_messages(env, created.id) == ["Fix the bug\nDetails here", "You seem stuck"]


async def test_a_nudge_as_a_queued_message_starts_keeps_it_first(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-58: the same for a queued message cut off on its way to the agent."""
    release_first = asyncio.Event()

    async def first_turn(run: FakeRun) -> None:
        await release_first.wait()
        await reply("first done")(run)

    env.provider.script(reply("prompt done"), first_turn, reply("B done"), reply("nudge done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "message A", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)
    await env.manager.send(created.id, "message B", [])
    in_gap, leave_gap = asyncio.Event(), asyncio.Event()
    original = env.attachments.file_dirs

    async def slow_file_dirs(session_id: str) -> tuple[Path, ...]:
        in_gap.set()
        await leave_gap.wait()
        return await original(session_id)

    monkeypatch.setattr(env.attachments, "file_dirs", slow_file_dirs)
    release_first.set()
    await asyncio.wait_for(in_gap.wait(), 5)

    await env.manager.send(created.id, "You seem stuck", [], interrupt=True)
    monkeypatch.setattr(env.attachments, "file_dirs", original)
    leave_gap.set()
    await until(lambda: len(run.inputs) == 4)
    await env.reach(created.id, SessionState.IDLE)

    assert texts(run) == ["Fix the bug\nDetails here", "message A", "message B", "You seem stuck"]
    assert await user_messages(env, created.id) == texts(run)
    assert await env.manager.queued(created.id) == []


async def test_two_messages_at_the_same_moment_run_one_after_the_other(env: Env) -> None:
    """BUG-17: the second is queued, not refused (D032)."""
    env.provider.script(reply("prompt done"), reply("one"), reply("two"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    first, second = await asyncio.gather(
        env.manager.send(created.id, "first", []), env.manager.send(created.id, "second", [])
    )
    await until(lambda: len(env.provider.runs[0].inputs) == 3)
    await env.reach(created.id, SessionState.IDLE)

    assert (first.queued_message is None) != (second.queued_message is None)
    assert sorted(texts(env.provider.runs[0])[1:]) == ["first", "second"]


async def test_a_message_sent_as_the_idle_close_runs_waits_for_the_agent_to_exit(
    env: Env,
) -> None:
    """BUG-16: Nest's own exiting process is not "open in Claude Code"."""
    env.manager = env.build(timedelta(milliseconds=20))
    env.provider.script(reply("done"), reply("again"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (first,) = env.provider.runs
    exiting, exit_now = asyncio.Event(), asyncio.Event()
    real_close = first.close

    async def slow_close() -> None:
        exiting.set()
        await exit_now.wait()  # the CLI runs its SessionEnd hooks, then exits
        await real_close()

    first.close = slow_close  # type: ignore[method-assign]
    env.claude.open_chat(4242, "sdk-1", entrypoint="sdk-py")
    env.alive.add(4242)
    await asyncio.wait_for(exiting.wait(), 5)

    sent = await env.manager.send(created.id, "one more thing", [])
    await asyncio.sleep(0.05)
    opened_too_early = len(env.provider.runs) > 1
    exit_now.set()
    await until(lambda: len(env.provider.runs) == 2 and bool(env.provider.runs[1].inputs))
    await env.reach(created.id, SessionState.IDLE)

    assert sent.queued_message is None
    assert not opened_too_early
    assert first.closed
    assert texts(env.provider.runs[1]) == ["one more thing"]


async def test_a_turn_that_ends_before_its_message_is_sent_still_closes_its_idle_run(
    env: Env,
) -> None:
    """BUG-19: the idle close is scheduled once the sending task is done."""
    env.manager = env.build(timedelta(milliseconds=10))
    gate = asyncio.Event()
    env.provider.send_gate = gate
    env.provider.script(reply("fast"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    gate.set()

    await until(lambda: env.provider.runs[0].closed)


async def test_a_document_attached_while_background_tasks_run_keeps_the_run(env: Env) -> None:
    """BUG-02: a new attachment folder waits for the next run, as a new effort does (D046)."""
    env.provider.script(background(1, reply("started a background agent")), reply("read it"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    doc = await env.attachments.save("notes.txt", b"hi", "text/plain")

    await env.manager.send(created.id, "read this", [doc.id])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)
    await env.reach(created.id, SessionState.IDLE)

    (run,) = env.provider.runs
    assert not run.closed
    assert run.inputs[1].file_paths == (doc.path,)


async def test_stop_while_the_turn_end_reads_the_queue_keeps_the_queue_waiting(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-59: the Stop is accepted, so it holds: the queued message waits."""
    release_first = asyncio.Event()

    async def first_turn(run: FakeRun) -> None:
        await release_first.wait()
        await reply("first done")(run)

    env.provider.script(reply("prompt done"), first_turn, reply("second done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "message A", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)
    await env.manager.send(created.id, "message B", [])
    in_gap, leave_gap = asyncio.Event(), asyncio.Event()
    original = env.queue.waiting

    async def slow_messages(session_id: str) -> list[QueuedMessage]:
        in_gap.set()
        await leave_gap.wait()
        return await original(session_id)

    monkeypatch.setattr(env.queue, "waiting", slow_messages)
    release_first.set()
    await asyncio.wait_for(in_gap.wait(), 5)

    await env.manager.interrupt(created.id)
    monkeypatch.setattr(env.queue, "waiting", original)
    leave_gap.set()
    await env.reach(created.id, SessionState.INTERRUPTED)

    assert texts(run) == ["Fix the bug\nDetails here", "message A"]
    assert [m.text for m in await env.manager.queued(created.id)] == ["message B"]
    assert not env.manager.busy(created.id)


async def test_a_message_sent_after_the_turn_ended_but_before_its_send_returned_starts(
    env: Env,
) -> None:
    """BUG-60: queued only because the sending task was still finishing, it starts then."""
    env.provider.script(reply("one"), reply("two"), reply("three"))
    created = await env.create(prompt="one", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    gate = asyncio.Event()
    env.provider.send_gate = gate

    await env.manager.send(created.id, "two", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)
    await env.reach(created.id, SessionState.IDLE)
    sent = await env.manager.send(created.id, "three", [])
    env.provider.send_gate = None
    gate.set()
    await until(lambda: len(run.inputs) == 3)
    await env.reach(created.id, SessionState.IDLE)

    assert sent.queued_message is not None
    assert texts(run) == ["one", "two", "three"]
    assert await env.manager.queued(created.id) == []


async def test_publishing_after_a_stop_keeps_the_queue_waiting(env: Env) -> None:
    """BUG-61: the end of publishing starts only what was sent meanwhile (D032, D054)."""
    env.provider.script(reply("one"), until_interrupted(), reply("three"))
    created = await env.create(prompt="one", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "two", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)
    await env.manager.send(created.id, "held", [])
    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)

    async with env.manager.publishing(created.id):
        pass

    assert texts(run) == ["one", "two"]
    assert [m.text for m in await env.manager.queued(created.id)] == ["held"]
    assert not env.manager.busy(created.id)
    assert (await env.states(created.id))[-1] == "interrupted"


async def test_the_engines_echo_of_a_mode_never_replaces_a_newer_choice(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-62: Claude Code reports the mode Nest just sent it; the user's later choice,
    saved while that reaches the run, stays (D048).
    """
    env.provider.script(reply("done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (run,) = env.provider.runs
    await env.manager.update(created.id, UpdateSession(permission_mode="plan"))
    sending, release = asyncio.Event(), asyncio.Event()
    original = run.set_permission_mode

    async def slow_set_permission_mode(mode: PermissionMode) -> None:
        sending.set()
        await release.wait()
        await original(mode)

    monkeypatch.setattr(run, "set_permission_mode", slow_set_permission_mode)
    newer = asyncio.ensure_future(
        env.manager.update(created.id, UpdateSession(permission_mode="default"))
    )
    await asyncio.wait_for(sending.wait(), 5)

    await run.sink.permission_mode("plan")
    release.set()
    await newer

    assert (await env.store.get(created.id)).permission_mode == "default"
    assert run.calls == [("set_permission_mode", "plan"), ("set_permission_mode", "default")]


async def test_stop_while_the_next_message_waits_for_the_last_send_ends_the_turn_once(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-64: the wait for the previous sending task does not cancel that task too."""
    turn_gate = asyncio.Event()

    async def quick(run: FakeRun) -> None:
        await turn_gate.wait()
        await reply("two")(run)

    env.provider.script(reply("one"), quick, reply("three"))
    created = await env.create(prompt="one", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (run,) = env.provider.runs
    send_gate = asyncio.Event()
    env.provider.send_gate = send_gate
    cancelled: list[str] = []
    original = run.send

    async def watched_send(user_input: UserInput) -> None:
        try:
            await original(user_input)
        except asyncio.CancelledError:
            cancelled.append(user_input.text)
            raise

    monkeypatch.setattr(run, "send", watched_send)
    await env.manager.send(created.id, "two", [])
    await until(lambda: len(run.inputs) == 2)
    await env.manager.send(created.id, "three", [])
    turn_gate.set()
    # The turn's end handed over to the next message, which waits for the sending task.
    await until(lambda: run.status_calls == 2)

    await env.manager.interrupt(created.id)
    await env.reach(created.id, SessionState.INTERRUPTED)
    env.provider.send_gate = None
    send_gate.set()
    await until(lambda: not env.manager.busy(created.id))

    assert cancelled == []
    assert (await env.states(created.id)).count("interrupted") == 1
    assert texts(run) == ["one", "two"]
    assert [m.text for m in await env.manager.queued(created.id)] == ["three"]


def note_attachments_read(env: Env, monkeypatch: pytest.MonkeyPatch) -> asyncio.Event:
    """Set once `send` read its attachments; it then waits for the turn end to settle."""
    read = asyncio.Event()
    original = env.attachments.for_session

    async def noted(ids: list[str], session_id: str | None) -> list[Attachment]:
        attachments = await original(ids, session_id)
        read.set()
        return attachments

    monkeypatch.setattr(env.attachments, "for_session", noted)
    return read


async def test_a_send_waiting_for_the_turn_end_never_starts_after_close(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-53: the stored state never flips from closed back to running."""
    env.provider.script(reply("done"), reply("A done"), reply("never"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    in_hook, release = asyncio.Event(), asyncio.Event()
    original = env.hooks.state_changed

    async def slow_hooks(session: Session) -> None:
        if session.state is SessionState.IDLE:
            in_hook.set()
            await release.wait()
        await original(session)

    monkeypatch.setattr(env.hooks, "state_changed", slow_hooks)
    await env.manager.send(created.id, "A", [])
    await asyncio.wait_for(in_hook.wait(), 5)
    read = note_attachments_read(env, monkeypatch)
    sending = asyncio.ensure_future(env.manager.send(created.id, "B", []))
    await asyncio.wait_for(read.wait(), 5)

    closed = await env.manager.close(created.id, remove_worktree=False)
    with pytest.raises(ConflictError):
        await sending

    assert closed.state is SessionState.CLOSED
    assert (await env.store.get(created.id)).state is SessionState.CLOSED
    assert (await env.states(created.id))[-1] == "closed"
    (run,) = env.provider.runs
    assert texts(run) == ["Fix the bug\nDetails here", "A"]
    assert not env.manager.busy(created.id)
    assert not env.manager.has_run(created.id)


async def test_a_send_while_the_worktree_is_removed_is_refused(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-53: closing keeps the session's live state, marked stopped, until it is closed."""
    env.provider.script(reply("done"), reply("never"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    removing, release = asyncio.Event(), asyncio.Event()
    original = env.worktrees.remove

    async def slow_remove(repo: RepoConfig, worktree: Worktree, delete_branch: bool) -> None:
        removing.set()
        await release.wait()
        await original(repo, worktree, delete_branch)

    monkeypatch.setattr(env.worktrees, "remove", slow_remove)
    closing = asyncio.ensure_future(env.manager.close(created.id, remove_worktree=True))
    await asyncio.wait_for(removing.wait(), 5)

    with pytest.raises(SessionBusyError):
        await env.manager.send(created.id, "B", [])
    release.set()
    closed = await closing

    assert closed.state is SessionState.CLOSED
    assert len(env.provider.runs) == 1
    assert not env.manager.busy(created.id)
    with pytest.raises(SessionClosedError):
        await env.manager.send(created.id, "C", [])


async def test_a_send_while_archiving_stops_the_run_is_refused_then_resumes(
    env: Env,
) -> None:
    """BUG-53: archiving keeps the chat open; the next message after it opens a new run."""
    env.provider.script(reply("done"), reply("resumed"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (first,) = env.provider.runs
    exiting, exit_now = asyncio.Event(), asyncio.Event()
    real_close = first.close

    async def slow_close() -> None:
        exiting.set()
        await exit_now.wait()
        await real_close()

    first.close = slow_close  # type: ignore[method-assign]
    archiving = asyncio.ensure_future(env.manager.update(created.id, UpdateSession(archived=True)))
    await asyncio.wait_for(exiting.wait(), 5)

    with pytest.raises(SessionBusyError):
        await env.manager.send(created.id, "too soon", [])
    exit_now.set()
    await archiving
    await env.manager.send(created.id, "after", [])
    await until(lambda: len(env.provider.runs) == 2 and bool(env.provider.runs[1].inputs))

    assert texts(env.provider.runs[1]) == ["after"]


async def test_a_send_during_shutdown_is_refused(env: Env) -> None:
    """BUG-53: nothing starts while the daemon stops its agents."""
    env.provider.script(reply("done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (first,) = env.provider.runs
    exiting, exit_now = asyncio.Event(), asyncio.Event()
    real_close = first.close

    async def slow_close() -> None:
        exiting.set()
        await exit_now.wait()
        await real_close()

    first.close = slow_close  # type: ignore[method-assign]
    stopping = asyncio.ensure_future(env.manager.shutdown())
    await asyncio.wait_for(exiting.wait(), 5)

    with pytest.raises(SessionBusyError):
        await env.manager.send(created.id, "too late", [])
    exit_now.set()
    await stopping

    assert len(env.provider.runs) == 1
    assert not env.manager.has_run(created.id)


async def test_a_stopped_live_session_starts_no_work() -> None:
    live = LiveSession("s1")
    await live.stop()

    with pytest.raises(SessionBusyError):
        live.start(lambda: asyncio.sleep(0))

    assert live.task is None


async def test_a_message_queued_and_cancelled_while_publishing_starts_nothing(env: Env) -> None:
    env.provider.script(reply("one"))
    created = await env.create(prompt="one", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    async with env.manager.publishing(created.id):
        sent = await env.manager.send(created.id, "never mind", [])
        assert sent.queued_message is not None
        await env.manager.cancel_queued(created.id, sent.queued_message.id)

    (run,) = env.provider.runs
    assert texts(run) == ["one"]
    assert not env.manager.busy(created.id)


async def test_closing_while_a_message_is_sent_keeps_nothing_to_resend(env: Env) -> None:
    """Only a nudge keeps a cut-off message (BUG-58); closing drops everything."""
    env.provider.script(reply("one"), hang())
    created = await env.create(prompt="one", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    env.provider.send_gate = asyncio.Event()
    await env.manager.send(created.id, "two", [])
    (run,) = env.provider.runs
    await until(lambda: len(run.inputs) == 2)

    closed = await env.manager.close(created.id, remove_worktree=False)

    assert closed.state is SessionState.CLOSED
    assert run.closed
    assert not env.manager.busy(created.id)
    assert (await env.states(created.id))[-1] == "closed"


async def test_two_archives_at_once_stop_the_run_once(env: Env) -> None:
    """Two devices archive the chat together; a message afterwards opens a new run."""
    env.provider.script(reply("done"), reply("resumed"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (first,) = env.provider.runs
    exiting, exit_now = asyncio.Event(), asyncio.Event()
    real_close = first.close

    async def slow_close() -> None:
        exiting.set()
        await exit_now.wait()
        await real_close()

    first.close = slow_close  # type: ignore[method-assign]
    archive = UpdateSession(archived=True)
    one = asyncio.ensure_future(env.manager.update(created.id, archive))
    two = asyncio.ensure_future(env.manager.update(created.id, archive))
    await asyncio.wait_for(exiting.wait(), 5)
    exit_now.set()
    await asyncio.gather(one, two)
    await env.manager.send(created.id, "after", [])
    await until(lambda: len(env.provider.runs) == 2 and bool(env.provider.runs[1].inputs))

    assert first.closed
    assert texts(env.provider.runs[1]) == ["after"]


async def test_a_mode_the_engine_reports_as_the_user_saves_it_is_saved_once(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    env.provider.script(reply("done"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (run,) = env.provider.runs
    sending, release = asyncio.Event(), asyncio.Event()
    original = run.set_permission_mode

    async def slow_set_permission_mode(mode: PermissionMode) -> None:
        sending.set()
        await release.wait()
        await original(mode)

    monkeypatch.setattr(run, "set_permission_mode", slow_set_permission_mode)
    choosing = asyncio.ensure_future(
        env.manager.update(created.id, UpdateSession(permission_mode="plan"))
    )
    await asyncio.wait_for(sending.wait(), 5)

    await run.sink.permission_mode("plan")
    release.set()
    await choosing

    updates = [
        event.payload["changes"]
        for event in await env.bus.session_events(created.id)
        if event.type == types.SESSION_UPDATED
    ]
    assert updates == [{"permission_mode": "plan"}]
    assert (await env.store.get(created.id)).permission_mode == "plan"
