from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from harness.approvals.models import ApprovalStatus
from harness.events import types
from harness.sessions.errors import SessionClosedError, SessionNotFoundError
from harness.sessions.models import SessionState, UpdateSession
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import ask, hang, reply
from tests.fakes import FakeClock
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


def update(**fields: object) -> UpdateSession:
    return UpdateSession.model_validate(fields)


async def updates(env: Env, session_id: str) -> list[JsonValue]:
    events = await env.bus.session_events(session_id)
    return [e.payload["changes"] for e in events if e.type == types.SESSION_UPDATED]


async def test_rename_and_pin_are_persisted_and_announced(env: Env, clock: FakeClock) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    renamed = await env.manager.update(created.id, update(title="  Login fix  ", pinned=True))
    again = await env.manager.update(created.id, update(title="Login fix", pinned=True))

    assert (renamed.title, renamed.pinned) == ("Login fix", True)
    assert again == renamed
    assert await updates(env, created.id) == [{"title": "Login fix", "pinned": True}]
    (event,) = [
        e for e in await env.bus.session_events(created.id) if e.type == types.SESSION_UPDATED
    ]
    assert event.payload["session"] == renamed.model_dump(mode="json")
    assert renamed.updated_at == clock.now()


async def test_archive_and_unarchive(env: Env, clock: FakeClock) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    clock.advance(timedelta(minutes=1))

    archived = await env.manager.update(created.id, update(archived=True))
    listed = await env.manager.list_sessions()
    hidden = await env.manager.list_sessions(archived=True)
    still = await env.manager.update(created.id, update(archived=True))
    restored = await env.manager.update(created.id, update(archived=False))

    assert archived.archived_at == clock.now()
    assert listed == []
    assert [s.id for s in hidden] == [created.id]
    assert still.archived_at == clock.now()
    assert restored.archived_at is None
    assert await updates(env, created.id) == [
        {"archived_at": clock.now().isoformat().replace("+00:00", "Z")},
        {"archived_at": None},
    ]


async def test_archiving_a_working_session_closes_its_run_and_keeps_the_worktree(
    env: Env,
) -> None:
    env.provider.script(ask("Bash", hang()))
    created = await env.create()
    session = await env.reach(created.id, SessionState.WAITING)

    archived = await env.manager.update(created.id, update(archived=True))

    assert archived.state is SessionState.INTERRUPTED
    assert archived.archived_at is not None
    assert env.provider.runs[0].closed is True
    assert session.worktree_path is not None
    assert session.worktree_path.is_dir()
    (item,) = await env.approvals.list_approvals()
    assert item.status is ApprovalStatus.EXPIRED
    assert item.resolution == {"reason": "the session was archived"}
    assert not env.manager.has_run(created.id)


async def test_archiving_an_idle_session_closes_its_run_but_keeps_its_state(env: Env) -> None:
    env.provider.script(reply("ok"), reply("again"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    assert env.manager.has_run(created.id)

    archived = await env.manager.update(created.id, update(archived=True))
    await env.manager.send(created.id, "continue", [])
    await until(lambda: len(env.provider.runs) == 2 and bool(env.provider.runs[1].inputs))
    resumed = await env.reach(created.id, SessionState.IDLE)

    assert archived.state is SessionState.IDLE
    assert env.provider.runs[0].closed is True
    assert env.provider.runs[1].spec.resume_id == "sdk-1"
    assert resumed.archived_at is not None


async def test_closed_sessions_can_be_organized_but_not_controlled(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.close(created.id, remove_worktree=False)

    organized = await env.manager.update(
        created.id, update(title="Old", pinned=True, archived=True)
    )

    assert (organized.title, organized.pinned) == ("Old", True)
    with pytest.raises(SessionClosedError):
        await env.manager.update(created.id, update(model="x"))
    with pytest.raises(SessionNotFoundError):
        await env.manager.update("nope", update(pinned=True))


async def test_list_filters_by_repo(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    assert [s.id for s in await env.manager.list_sessions(repo="repo")] == [created.id]
    assert await env.manager.list_sessions(repo="other") == []
