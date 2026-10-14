"""Changes that land while a session's agent run opens or its worktree is created."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.approvals.models import ApprovalStatus
from harness.sessions.models import SessionState, UpdateSession
from harness.storage.db import Database
from tests.fake_provider import plan, reply
from tests.fakes import FakeClock
from tests.git_support import git
from tests.session_support import Env, gate_worktree_add

PROMPT = "Fix the bug\nDetails here"


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def opening(env: Env, **fields: object) -> tuple[str, asyncio.Event]:
    """A new session whose agent run is opening; setting the returned gate lets it open."""
    gate = asyncio.Event()
    env.provider.open_gate = gate
    created = await env.create(PROMPT, **fields)
    await env.reach(created.id, SessionState.RUNNING)
    return created.id, gate


async def test_leaving_bypass_while_the_run_opens_reaches_the_run(env: Env) -> None:
    env.provider.script(reply("ok"))
    session_id, gate = await opening(env, permission_mode="bypassPermissions")

    await env.manager.update(session_id, UpdateSession(permission_mode="default"))
    gate.set()
    await env.reach(session_id, SessionState.IDLE)

    (run,) = env.provider.runs
    assert run.spec.permission_mode == "bypassPermissions"
    assert run.calls == [("set_permission_mode", "default")]
    assert (await env.store.get(session_id)).permission_mode == "default"


async def test_entering_bypass_while_the_run_opens_reopens_it_before_the_message(
    env: Env,
) -> None:
    env.provider.script(reply("ok"))
    session_id, gate = await opening(env)

    await env.manager.update(session_id, UpdateSession(permission_mode="bypassPermissions"))
    gate.set()
    await env.reach(session_id, SessionState.IDLE)

    first, second = env.provider.runs
    assert first.spec.permission_mode == "acceptEdits"
    assert first.closed is True
    assert first.inputs == []
    assert second.spec.permission_mode == "bypassPermissions"
    assert [item.text for item in second.inputs] == [PROMPT]
    assert second.calls == []


async def test_a_model_chosen_while_the_run_opens_reaches_the_run(env: Env) -> None:
    env.provider.script(reply("ok"))
    session_id, gate = await opening(env)

    await env.manager.update(session_id, UpdateSession(model="claude-opus-5"))
    gate.set()
    await env.reach(session_id, SessionState.IDLE)

    (run,) = env.provider.runs
    assert run.spec.model == "claude-sonnet-5"
    assert run.calls == [("set_model", "claude-opus-5")]


async def test_an_effort_chosen_while_the_run_opens_reopens_it(env: Env) -> None:
    env.provider.script(reply("ok"))
    session_id, gate = await opening(env)

    await env.manager.update(session_id, UpdateSession(effort="high"))
    gate.set()
    await env.reach(session_id, SessionState.IDLE)

    first, second = env.provider.runs
    assert first.closed is True
    assert first.inputs == []
    assert second.spec.effort == "high"
    assert [item.text for item in second.inputs] == [PROMPT]


async def test_a_mode_the_engine_switched_to_itself_is_known_to_the_run(env: Env) -> None:
    """An approved plan moves the engine to acceptEdits; going back to plan must reach it."""
    env.provider.script(plan("# Plan", reply("done")))
    created = await env.create(PROMPT, permission_mode="plan")
    await env.reach(created.id, SessionState.WAITING)
    (item,) = await env.approvals.list_approvals(ApprovalStatus.PENDING)
    await env.approvals.resolve(item.id, {"decision": "approve"})
    await env.reach(created.id, SessionState.IDLE)
    assert (await env.store.get(created.id)).permission_mode == "acceptEdits"

    await env.manager.update(created.id, UpdateSession(permission_mode="plan"))

    assert env.provider.runs[0].calls == [("set_permission_mode", "plan")]


async def test_interrupting_while_the_worktree_is_created_keeps_the_chat_usable(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = gate_worktree_add(monkeypatch)
    env.provider.script(reply("on it"))
    created = await env.create(PROMPT)
    await asyncio.wait_for(started.wait(), 5)

    await env.manager.interrupt(created.id)
    release.set()
    session = await env.reach(created.id, SessionState.INTERRUPTED)

    assert session.worktree_path is not None
    assert session.cwd == session.worktree_path
    assert str(session.worktree_path) in git(env.repo_path, "worktree", "list")
    assert "session.workspace" in await env.event_types(created.id)
    await env.manager.send(created.id, "carry on", [])
    await env.reach(created.id, SessionState.IDLE)
    assert env.provider.runs[0].spec.cwd == session.worktree_path


async def test_closing_while_the_worktree_is_created_removes_it_and_its_branch(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = gate_worktree_add(monkeypatch)
    created = await env.create(PROMPT)
    await asyncio.wait_for(started.wait(), 5)

    # Interrupted first, then closed: the second cancellation must not cut the wait short.
    await env.manager.interrupt(created.id)
    closing = asyncio.ensure_future(env.manager.close(created.id, remove_worktree=True))
    await asyncio.sleep(0.05)
    release.set()
    closed = await closing

    assert closed.state is SessionState.CLOSED
    assert closed.worktree_path is not None
    assert not closed.worktree_path.exists()
    assert str(closed.worktree_path) not in git(env.repo_path, "worktree", "list")
    assert str(closed.branch) not in git(env.repo_path, "branch")
    assert env.provider.runs == []


async def test_a_worktree_add_failing_after_an_interrupt_fails_the_session(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    started, release = gate_worktree_add(monkeypatch, fail=True)
    created = await env.create(PROMPT)
    await asyncio.wait_for(started.wait(), 5)

    await env.manager.interrupt(created.id)
    release.set()
    failed = await env.reach(created.id, SessionState.FAILED)

    assert failed.worktree_path is None
    assert failed.last_error is not None
    assert "no space left" in failed.last_error
