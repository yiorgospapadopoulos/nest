"""B59: forking a chat from one of its messages into a new chat."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.errors import InvalidInputError
from nestd.events import types
from nestd.providers.base import ForkPoint
from nestd.sessions.errors import (
    CannotRewindError,
    PixieChatError,
    SessionBusyError,
    SessionClosedError,
)
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, echoed, reply
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


async def two_turns(env: Env, mode: str = "in_place") -> tuple[str, int, int]:
    env.provider.script(echoed("cp-1", reply("one")), echoed("cp-2", reply("two")))
    env.provider.fork_points = {
        ("sdk-1", "cp-1"): ForkPoint(None),
        ("sdk-1", "cp-2"): ForkPoint("a-1"),
    }
    created = await env.create(prompt="first", mode=mode)
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "second", [])
    await until_results(env, created.id, 2)
    events = await env.bus.session_events(created.id)
    first, second = [
        e.id for e in events if e.type == types.SESSION_USER_MESSAGE and e.id is not None
    ]
    return created.id, first, second


async def texts(env: Env, session_id: str) -> list[str]:
    shown: list[str] = []
    for event in await env.bus.session_events(session_id):
        if event.type == types.SESSION_USER_MESSAGE:
            shown.append(f"user: {event.payload['text']}")
        elif event.type == types.SESSION_MESSAGE:
            blocks = event.payload["blocks"]
            assert isinstance(blocks, list)
            shown.extend(f"agent: {b['text']}" for b in blocks if isinstance(b, dict))
    return shown


async def test_a_fork_is_a_new_chat_with_the_conversation_before_the_message(
    env: Env,
) -> None:
    source_id, _, second = await two_turns(env)
    source_events = await env.bus.session_events(source_id)

    fork = await env.manager.fork(source_id, second)

    session = fork.session
    source = await env.store.get(source_id)
    assert (fork.text, fork.attachments) == ("second", [])
    assert session.id != source_id
    assert (session.repo, session.mode, session.cwd) == ("repo", "in_place", source.cwd)
    assert session.title == f"{source.title} (fork)"
    assert (session.model, session.effort, session.permission_mode) == (
        source.model,
        source.effort,
        source.permission_mode,
    )
    assert session.state is SessionState.IDLE
    assert session.provider_session_id is None
    assert (session.fork_from, session.fork_at, session.fork_drops) == ("sdk-1", "a-1", "cp-2")
    assert await texts(env, session.id) == ["user: first", "agent: one"]
    events = await env.bus.session_events(session.id)
    assert [e.type for e in events[:2]] == [types.SESSION_CREATED, types.SESSION_STATE]
    assert types.SESSION_WORKSPACE not in [e.type for e in events]
    copied = next(e.id for e in events if e.type == types.SESSION_USER_MESSAGE)
    assert copied is not None
    assert await env.store.checkpoint(session.id, copied) == "cp-1"
    # The original is untouched, and its run goes on.
    assert await env.bus.session_events(source_id) == source_events
    assert not env.provider.runs[0].closed
    listed = [s.id for s in await env.manager.list_sessions("repo")]
    assert session.id in listed


async def test_the_forks_first_message_continues_the_cut_conversation(env: Env) -> None:
    source_id, _, second = await two_turns(env)
    fork = await env.manager.fork(source_id, second)
    env.provider.script(echoed("cp-9", reply("forked answer", provider_session_id="sdk-9")))

    await env.manager.send(fork.session.id, "second, differently", [])
    # The copied transcript holds the first turn's result.
    await until_results(env, fork.session.id, 2)

    run = env.provider.runs[-1]
    assert (run.spec.resume_id, run.spec.resume_at, run.spec.drops_turn) == (
        "sdk-1",
        "a-1",
        "cp-2",
    )
    session = await env.store.get(fork.session.id)
    assert session.provider_session_id == "sdk-9"
    assert (session.fork_from, session.fork_at, session.fork_drops) == (None, None, None)
    # The original keeps its Claude Code session.
    owner = await env.manager.find_by_provider_session("sdk-1")
    assert owner is not None
    assert owner.id == source_id
    assert (await env.store.get(source_id)).provider_session_id == "sdk-1"


async def test_a_fork_from_the_first_message_starts_afresh(env: Env) -> None:
    source_id, first, _ = await two_turns(env)

    fork = await env.manager.fork(source_id, first)
    env.provider.script(reply("fresh", provider_session_id="sdk-5"))
    await env.manager.send(fork.session.id, "first, differently", [])
    await until_results(env, fork.session.id, 1)

    assert fork.text == "first"
    assert (fork.session.fork_from, fork.session.fork_at) == (None, None)
    assert env.provider.runs[-1].spec.resume_id is None
    assert await texts(env, fork.session.id) == ["user: first, differently", "agent: fresh"]


async def test_a_forked_worktree_chat_gets_its_own_worktree_from_the_branch(env: Env) -> None:
    source_id, _, second = await two_turns(env, mode="worktree")
    source = await env.store.get(source_id)
    assert source.worktree_path is not None
    assert source.branch is not None
    git(source.worktree_path, "commit", "--allow-empty", "-q", "-m", "work so far")
    tip = git(source.worktree_path, "rev-parse", "HEAD").strip()

    fork = await env.manager.fork(source_id, second)
    assert (fork.session.mode, fork.session.cwd, fork.session.worktree_path) == (
        "worktree",
        None,
        None,
    )
    assert fork.session.base_ref == tip
    env.provider.script(reply("in my own worktree", provider_session_id="sdk-7"))
    await env.manager.send(fork.session.id, "go on", [])
    await until_results(env, fork.session.id, 2)

    session = await env.store.get(fork.session.id)
    assert session.worktree_path is not None
    assert session.worktree_path != source.worktree_path
    assert session.branch != source.branch
    assert git(session.worktree_path, "rev-parse", "HEAD").strip() == tip
    assert env.provider.runs[-1].spec.cwd == session.worktree_path
    states = await env.states(session.id)
    assert states[-4:] == ["idle", "starting", "running", "idle"]


async def test_a_worktree_fork_without_the_branch_starts_from_the_chats_base(env: Env) -> None:
    source_id, _, second = await two_turns(env, mode="worktree")
    source = await env.store.get(source_id)

    await env.store.update(source_id, branch="gone-branch")
    from_gone = await env.manager.fork(source_id, second)
    await env.store.update(source_id, branch=None)
    from_none = await env.manager.fork(source_id, second)

    assert from_gone.session.base_ref == source.base_ref
    assert from_none.session.base_ref == source.base_ref


async def test_forking_is_refused_while_a_turn_runs(env: Env) -> None:
    source_id, _, second = await two_turns(env)
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("done")(run)

    env.provider.script(slow)
    await env.manager.send(source_id, "third", [])
    await env.reach(source_id, SessionState.RUNNING)

    with pytest.raises(SessionBusyError, match="no turn is running"):
        await env.manager.fork(source_id, second)
    gate.set()


async def test_forking_needs_a_message_claude_code_has(env: Env) -> None:
    source_id, _, second = await two_turns(env)
    env.provider.fork_points = {}

    with pytest.raises(CannotRewindError, match="does not have this message"):
        await env.manager.fork(source_id, second)


async def test_forking_needs_a_checkpointed_message(env: Env) -> None:
    env.provider.script(reply("one"))
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    events = await env.bus.session_events(created.id)
    message = next(e.id for e in events if e.type == types.SESSION_USER_MESSAGE)
    assert message is not None

    with pytest.raises(CannotRewindError, match="no file checkpoint"):
        await env.manager.fork(created.id, message)


async def test_a_pixie_chat_and_a_closed_chat_are_not_forked(env: Env) -> None:
    source_id, _, second = await two_turns(env)

    await env.db.execute("PRAGMA foreign_keys = OFF")
    await env.store.update(source_id, pixie_id="p1")
    with pytest.raises(PixieChatError):
        await env.manager.fork(source_id, second)
    await env.store.update(source_id, pixie_id=None, state=SessionState.CLOSED)
    with pytest.raises(SessionClosedError):
        await env.manager.fork(source_id, second)


async def test_a_chat_of_a_removed_project_is_not_forked(env: Env) -> None:
    source_id, _, second = await two_turns(env)
    await env.store.update(source_id, repo="elsewhere")

    with pytest.raises(InvalidInputError):
        await env.manager.fork(source_id, second)


async def test_a_fork_runs_beside_its_original(env: Env) -> None:
    source_id, _, second = await two_turns(env)
    fork = await env.manager.fork(source_id, second)
    env.provider.script(reply("fork says"), reply("original says"))

    await env.manager.send(fork.session.id, "fork", [])
    await until_results(env, fork.session.id, 2)
    await env.manager.send(source_id, "original", [])
    await until_results(env, source_id, 3)

    await until(lambda: len(env.provider.runs) == 2)
    assert await texts(env, source_id) == [
        "user: first",
        "agent: one",
        "user: second",
        "agent: two",
        "user: original",
        "agent: original says",
    ]


async def test_a_copied_message_without_a_checkpoint_stays_without_one(env: Env) -> None:
    env.provider.script(reply("one"), echoed("cp-2", reply("two")))
    env.provider.fork_points = {("sdk-1", "cp-2"): ForkPoint("a-1")}
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "second", [])
    await until_results(env, created.id, 2)
    events = await env.bus.session_events(created.id)
    second = [e.id for e in events if e.type == types.SESSION_USER_MESSAGE][1]
    assert second is not None

    fork = await env.manager.fork(created.id, second)

    copied = next(
        e.id
        for e in await env.bus.session_events(fork.session.id)
        if e.type == types.SESSION_USER_MESSAGE
    )
    assert copied is not None
    assert await env.store.checkpoint(fork.session.id, copied) is None


async def test_the_forked_messages_attachments_are_copied_for_the_fork(env: Env) -> None:
    env.provider.script(echoed("cp-1", reply("one")), echoed("cp-2", reply("two")))
    env.provider.fork_points = {("sdk-1", "cp-2"): ForkPoint("a-1")}
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    image = await env.attachments.save("shot.png", b"\x89PNG", "image/png")
    gone = await env.attachments.save("gone.txt", b"bye", "text/plain")
    await env.manager.send(created.id, "look", [image.id, gone.id])
    await until_results(env, created.id, 2)
    gone.path.unlink()
    events = await env.bus.session_events(created.id)
    second = [e.id for e in events if e.type == types.SESSION_USER_MESSAGE][1]
    assert second is not None

    fork = await env.manager.fork(created.id, second)
    (copy,) = fork.attachments
    env.provider.script(reply("seen", provider_session_id="sdk-8"))
    await env.manager.send(fork.session.id, fork.text, [copy.id])
    await until_results(env, fork.session.id, 2)

    assert copy.id != image.id
    assert (copy.filename, copy.media_type, copy.size) == ("shot.png", "image/png", 4)
    assert env.provider.runs[-1].inputs[-1].images[0].media_type == "image/png"
