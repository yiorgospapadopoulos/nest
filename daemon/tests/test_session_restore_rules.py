"""When files can be restored, and what a restore in progress does to the chat (B34:
BUG-88, BUG-89, BUG-94, BUG-104).
"""

import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.events import types
from harness.providers.base import RewindResult
from harness.sessions.errors import NoTurnInProgressError, NoWorkspaceError, SessionBusyError
from harness.sessions.live import LiveSession
from harness.sessions.models import SessionState, UpdateSession
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import (
    FakeRun,
    Turn,
    background,
    echoed,
    engine_error,
    reply,
    until_interrupted,
)
from tests.fakes import FakeClock
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def first_message(env: Env, session_id: str) -> int:
    events = await env.bus.session_events(session_id)
    return next(e.id for e in events if e.type == types.SESSION_USER_MESSAGE and e.id is not None)


async def idle_chat(env: Env, *later: Turn) -> tuple[str, int, FakeRun]:
    """A chat whose first message has a checkpoint; `later` are more scripted turns."""
    env.provider.script(echoed("msg-1", reply("one")), *later)
    created = await env.create(mode="in_place", allow_dirty=True)
    await env.reach(created.id, SessionState.IDLE)
    return created.id, await first_message(env, created.id), env.provider.runs[0]


class SlowRestore:
    """Holds the run's restore until released."""

    def __init__(self, run: FakeRun, monkeypatch: pytest.MonkeyPatch) -> None:
        self.started, self.release = asyncio.Event(), asyncio.Event()
        self._rewind = run.rewind_files
        monkeypatch.setattr(run, "rewind_files", self.rewind_files)

    async def rewind_files(self, checkpoint_id: str, dry_run: bool) -> RewindResult:
        self.started.set()
        await self.release.wait()
        return await self._rewind(checkpoint_id, dry_run)


async def states_since(env: Env, session_id: str, count: int) -> list[object]:
    return (await env.states(session_id))[count:]


async def test_stop_during_a_restore_neither_cancels_it_nor_marks_the_chat_interrupted(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-88: a restore is not a turn; Stop has nothing to stop."""
    session_id, message, run = await idle_chat(env, reply("two"))
    slow = SlowRestore(run, monkeypatch)
    restoring = asyncio.ensure_future(env.manager.rewind(session_id, message, dry_run=False))
    await asyncio.wait_for(slow.started.wait(), 5)

    with pytest.raises(NoTurnInProgressError):
        await env.manager.interrupt(session_id)
    slow.release.set()
    restored = await restoring
    before = len(await env.states(session_id))
    await env.manager.send(session_id, "two", [])
    await until(lambda: len(run.inputs) == 2)
    await env.reach(session_id, SessionState.IDLE)

    assert restored.can_rewind is True
    assert await states_since(env, session_id, before) == ["running", "idle"]


async def test_a_nudge_during_a_restore_waits_for_it_then_starts(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-88: the nudge's message is queued; the restore finishes and nothing ends
    interrupted.
    """
    session_id, message, run = await idle_chat(env, reply("answer"))
    slow = SlowRestore(run, monkeypatch)
    restoring = asyncio.ensure_future(env.manager.rewind(session_id, message, dry_run=False))
    await asyncio.wait_for(slow.started.wait(), 5)
    before = len(await env.states(session_id))

    sent = await env.manager.send(session_id, "You seem stuck", [], interrupt=True)
    slow.release.set()
    restored = await restoring
    await until(lambda: len(run.inputs) == 2)
    await env.reach(session_id, SessionState.IDLE)

    assert sent.queued_message is not None
    assert restored.can_rewind is True
    assert [i.text for i in run.inputs] == ["Fix the bug\nDetails here", "You seem stuck"]
    assert await states_since(env, session_id, before) == ["running", "idle"]


async def test_a_turn_the_agent_starts_during_a_restore_runs_after_it(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-89: it is followed like any turn instead of running unseen beside the restore."""
    session_id, message, run = await idle_chat(env)
    slow = SlowRestore(run, monkeypatch)
    restoring = asyncio.ensure_future(env.manager.rewind(session_id, message, dry_run=True))
    await asyncio.wait_for(slow.started.wait(), 5)
    before = len(await env.states(session_id))

    run.emit(reply("a background task finished"))
    await asyncio.sleep(0.05)
    during = await states_since(env, session_id, before)
    slow.release.set()
    await restoring

    async def tracked() -> bool:
        return await states_since(env, session_id, before) == ["running", "idle"]

    await until(tracked)
    assert during == []
    assert not env.manager.busy(session_id)


async def test_a_restore_leaves_work_started_meanwhile_alone() -> None:
    """BUG-89: the end of a restore clears only its own task."""
    live = LiveSession("s1")
    other = asyncio.ensure_future(asyncio.sleep(0))

    async with live.hold():
        live.task = other

    assert live.task is other
    await other


@pytest.mark.parametrize(
    ("turn", "ended"),
    [
        (until_interrupted(), SessionState.INTERRUPTED),
        (engine_error("API Error: 500"), SessionState.FAILED),
    ],
)
async def test_files_can_be_restored_after_a_stop_or_a_failure(
    env: Env, turn: Turn, ended: SessionState
) -> None:
    """BUG-104: whenever no turn runs."""
    session_id, message, run = await idle_chat(env, turn)
    await env.manager.send(session_id, "two", [])
    await until(lambda: len(run.inputs) == 2)
    if ended is SessionState.INTERRUPTED:
        await env.manager.interrupt(session_id)
    await env.reach(session_id, ended)

    preview = await env.manager.rewind(session_id, message, dry_run=True)

    assert preview.can_rewind is True


async def test_files_are_not_restored_while_background_tasks_run(env: Env) -> None:
    """BUG-89, BUG-104: they could still change the files after the restore."""
    session_id, message, run = await idle_chat(env)
    run.emit(background(1))
    await until(lambda: env.manager.background_running(session_id))

    with pytest.raises(SessionBusyError) as refused:
        await env.manager.rewind(session_id, message, dry_run=True)

    assert refused.value.payload() == {
        "detail": "Files cannot be restored while the agent's background tasks run. "
        "Wait for them to finish."
    }
    assert ("rewind_files", ("msg-1", True)) not in run.calls


async def test_files_are_not_restored_while_the_work_is_published(env: Env) -> None:
    session_id, message, run = await idle_chat(env)

    async with env.manager.publishing(session_id):
        with pytest.raises(SessionBusyError) as refused:
            await env.manager.rewind(session_id, message, dry_run=True)

    assert str(refused.value) == (
        "Files cannot be restored while harness commits or pushes this chat's work. "
        "Try again when that is done."
    )
    assert run.calls == []


async def test_files_are_not_restored_in_an_archived_chat(env: Env) -> None:
    session_id, message, _run = await idle_chat(env)
    await env.manager.update(session_id, UpdateSession(archived=True))

    with pytest.raises(SessionBusyError) as refused:
        await env.manager.rewind(session_id, message, dry_run=True)

    assert str(refused.value) == "Files cannot be restored in an archived chat. Unarchive it first."
    assert len(env.provider.runs) == 1


async def test_files_are_not_restored_while_a_turn_runs(env: Env) -> None:
    session_id, message, run = await idle_chat(env, until_interrupted())
    await env.manager.send(session_id, "two", [])
    await until(lambda: len(run.inputs) == 2)

    with pytest.raises(SessionBusyError) as refused:
        await env.manager.rewind(session_id, message, dry_run=True)

    assert str(refused.value) == (
        "Files can be restored only when no turn is running. Wait for the turn to end, or stop it."
    )


async def test_a_preview_never_starts_claude_code(env: Env) -> None:
    """BUG-94: without an open run it says why; restoring itself may resume the run."""
    session_id, message, run = await idle_chat(env)
    await env.manager.close_idle_run(session_id)
    assert run.closed

    preview = await env.manager.rewind(session_id, message, dry_run=True)

    assert preview == RewindResult(
        can_rewind=False,
        error="Claude Code is not running for this chat, so the files to restore cannot be "
        "listed. Send a message to start it again, then try again.",
    )
    assert len(env.provider.runs) == 1
    assert not env.manager.busy(session_id)


async def test_a_deleted_folder_is_reported(env: Env) -> None:
    """BUG-94: a readable conflict, not a server error, and no run opens in it."""
    env.provider.script(echoed("msg-1", reply("one")))
    created = await env.create()
    session = await env.reach(created.id, SessionState.IDLE)
    message = await first_message(env, created.id)
    await env.manager.close_idle_run(created.id)
    assert session.worktree_path is not None
    shutil.rmtree(session.worktree_path)

    for dry_run in (True, False):
        with pytest.raises(NoWorkspaceError, match="no longer exists"):
            await env.manager.rewind(created.id, message, dry_run=dry_run)

    assert len(env.provider.runs) == 1
