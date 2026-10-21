import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.approvals.models import ApprovalKind
from nestd.events import types
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import ask, hang, reply
from tests.fakes import FakeClock
from tests.git_support import git
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def rows(env: Env, table: str, session_id: str) -> int:
    row = await env.db.fetch_one(
        f"SELECT COUNT(*) AS n FROM {table} WHERE session_id = ?",  # noqa: S608
        (session_id,),
    )
    assert row is not None
    return row["n"]


async def deleted_events(env: Env) -> list[object]:
    found = await env.db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.SESSION_DELETED,)
    )
    return [(row["session_id"], row["payload"]) for row in found]


async def test_purge_deletes_the_session_and_everything_it_left(env: Env) -> None:
    env.provider.script(reply("ok"))
    attachment = await env.attachments.save("notes.txt", b"x", "text/plain")
    created = await env.create(attachment_ids=[attachment.id])
    session = await env.reach(created.id, SessionState.IDLE)
    await env.approvals.add(created.id, ApprovalKind.REVIEW, {}, "review")
    assert session.worktree_path is not None

    await env.manager.purge(created.id)

    with pytest.raises(SessionNotFoundError):
        await env.manager.get(created.id)
    for table in ("approvals", "attachments", "events"):
        assert await rows(env, table, created.id) == 0
    assert not attachment.path.parent.exists()
    assert not session.worktree_path.exists()
    assert str(session.branch) in git(env.repo_path, "branch")
    assert env.provider.runs[0].closed is True
    assert await deleted_events(env) == [(None, f'{{"session_id": "{created.id}"}}')]
    assert env.hooks.purges == [created.id]


async def test_purge_stops_a_working_session(env: Env) -> None:
    env.provider.script(ask("Bash", hang()))
    created = await env.create()
    await env.reach(created.id, SessionState.WAITING)

    await env.manager.purge(created.id)

    assert env.provider.runs[0].closed is True
    assert await rows(env, "approvals", created.id) == 0
    assert not env.manager.has_run(created.id)


async def test_purge_after_close_with_the_worktree_already_removed(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.close(created.id, remove_worktree=True)

    await env.manager.purge(created.id)

    with pytest.raises(SessionNotFoundError):
        await env.manager.get(created.id)


async def test_purge_never_touches_an_in_place_checkout(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.purge(created.id)

    assert (env.repo_path / "README.md").is_file()


async def test_purge_of_a_session_whose_repo_is_no_longer_registered(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    session = await env.reach(created.id, SessionState.IDLE)
    (env.paths.repos_dir / "repo.toml").unlink()

    await env.manager.purge(created.id)

    with pytest.raises(SessionNotFoundError):
        await env.manager.get(created.id)
    # Without the repo's config, git cannot clean up; the worktree directory stays.
    assert session.worktree_path is not None
    assert session.worktree_path.is_dir()


async def test_purge_after_the_repo_folder_was_deleted(env: Env) -> None:
    env.provider.script(reply("ok"))
    attachment = await env.attachments.save("notes.txt", b"x", "text/plain")
    created = await env.create(attachment_ids=[attachment.id])
    session = await env.reach(created.id, SessionState.IDLE)
    await env.approvals.add(created.id, ApprovalKind.REVIEW, {}, "review")
    shutil.rmtree(env.repo_path)

    await env.manager.purge(created.id)

    with pytest.raises(SessionNotFoundError):
        await env.manager.get(created.id)
    for table in ("approvals", "attachments", "events"):
        assert await rows(env, table, created.id) == 0
    assert not attachment.path.parent.exists()
    # Git cannot clean up without the repo; the leftover worktree directory is deleted.
    assert session.worktree_path is not None
    assert not session.worktree_path.exists()
    assert await deleted_events(env) == [(None, f'{{"session_id": "{created.id}"}}')]


async def test_purge_of_a_starting_session(env: Env) -> None:
    env.provider.open_gate = asyncio.Event()
    created = await env.create()
    await until(lambda: env.manager.has_run(created.id))

    await env.manager.purge(created.id)

    with pytest.raises(SessionNotFoundError):
        await env.manager.get(created.id)


async def test_purge_of_an_unknown_session(env: Env) -> None:
    with pytest.raises(SessionNotFoundError):
        await env.manager.purge("nope")
