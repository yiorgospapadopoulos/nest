"""B145: a chat's files come back from Nest's git snapshot of each message, on any engine."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.events import types
from nestd.providers.base import ForkPoint
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from tests.fake_provider import echoed, reply
from tests.fakes import FakeClock
from tests.git_support import git
from tests.session_support import Env
from tests.test_session_control import until_results


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def user_messages(env: Env, session_id: str) -> list[int]:
    events = await env.bus.session_events(session_id)
    return [e.id for e in events if e.type == types.SESSION_USER_MESSAGE and e.id is not None]


async def test_files_go_back_to_before_a_message_without_the_engines_help(env: Env) -> None:
    # The engine reports no checkpoint of its own, as Codex and ACP engines do not.
    env.provider.script(reply("one"), reply("two"))
    repo = env.repo_path
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    # What the first turn changed, by any tool or command.
    (repo / "README.md").write_text("edited\n", encoding="utf-8")
    (repo / "made.txt").write_text("new\n", encoding="utf-8")
    await env.manager.send(created.id, "and more", [])
    await until_results(env, created.id, 2)
    (repo / "made.txt").unlink()
    first, _ = await user_messages(env, created.id)

    preview = await env.manager.rewind(created.id, first, dry_run=True)
    restored = await env.manager.rewind(created.id, first, dry_run=False)

    assert preview.can_rewind
    assert sorted(preview.files_changed) == ["README.md"]
    assert restored.files_changed == ["README.md"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert not (repo / "made.txt").exists()
    assert env.provider.runs[0].calls == []


async def test_a_forked_worktree_chat_restores_its_own_worktree(env: Env) -> None:
    """Its first messages' snapshots were taken in the original's worktree, which an undo
    in the fork must leave alone.
    """
    env.provider.script(echoed("cp-1", reply("one")), echoed("cp-2", reply("two")))
    env.provider.fork_points = {("sdk-1", "cp-2"): ForkPoint("a-1")}
    source = await env.create(prompt="first", mode="worktree")
    await env.reach(source.id, SessionState.IDLE)
    await env.manager.send(source.id, "second", [])
    await until_results(env, source.id, 2)
    _, second = await user_messages(env, source.id)
    fork = await env.manager.fork(source.id, second)
    env.provider.script(reply("go", provider_session_id="sdk-7"))
    await env.manager.send(fork.session.id, "go on", [])
    await until_results(env, fork.session.id, 2)
    original = (await env.store.get(source.id)).worktree_path
    own = (await env.store.get(fork.session.id)).worktree_path
    assert original is not None
    assert own is not None
    (original / "README.md").write_text("the original's work\n", encoding="utf-8")
    (own / "README.md").write_text("the fork's work\n", encoding="utf-8")
    copied = (await user_messages(env, fork.session.id))[0]

    await env.manager.rewind(fork.session.id, copied, dry_run=False)

    assert (own / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (original / "README.md").read_text(encoding="utf-8") == "the original's work\n"


async def test_a_deleted_chat_takes_its_snapshots_with_it(env: Env) -> None:
    env.provider.script(reply("one"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    assert git(env.repo_path, "for-each-ref", "refs/nest/") != ""

    await env.manager.purge(created.id)

    assert git(env.repo_path, "for-each-ref", "refs/nest/") == ""
