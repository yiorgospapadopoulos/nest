import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.claude_sessions.errors import ChatOpenElsewhereError
from nestd.errors import InvalidInputError
from nestd.events import types
from nestd.repos.service import RepoFolderMissingError
from nestd.sessions.errors import NoWorkspaceError
from nestd.sessions.models import ChatImport, SessionState, UpdateSession
from nestd.storage.db import Database
from tests.async_support import until
from tests.claude_support import CHAT_A
from tests.fake_provider import reply
from tests.fakes import FakeClock
from tests.git_support import commit_file, git
from tests.session_support import Env

HISTORY: list[tuple[str, dict[str, JsonValue]]] = [
    (types.SESSION_USER_MESSAGE, {"text": "Fix it", "attachments": []}),
    (types.SESSION_MESSAGE, {"blocks": [{"type": "text", "text": "Done"}]}),
]


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


def chat(env: Env, cwd: Path | None = None, repo: str = "repo") -> ChatImport:
    return ChatImport(
        repo=repo,
        title="Fix it",
        prompt="Fix it please",
        cwd=cwd or env.repo_path.resolve(),
        provider_session_id=CHAT_A,
        history=HISTORY,
    )


async def answered(env: Env, session_id: str) -> None:
    async def done() -> bool:
        return await env.states(session_id) == ["idle", "running", "idle"]

    await until(done)


async def test_adopting_a_chat_creates_an_idle_in_place_session_with_its_history(
    env: Env,
) -> None:
    session = await env.manager.adopt(chat(env))

    assert session.state is SessionState.IDLE
    assert session.mode == "in_place"
    assert session.cwd == env.repo_path.resolve()
    assert session.worktree_path is None
    assert session.branch is None
    assert session.provider_session_id == CHAT_A
    assert (session.title, session.prompt) == ("Fix it", "Fix it please")
    assert session.base_ref == git(env.repo_path, "rev-parse", "HEAD").strip()
    assert (session.model, session.effort, session.permission_mode) == (
        "claude-sonnet-5",
        "medium",
        "acceptEdits",
    )
    events = await env.bus.session_events(session.id)
    assert [(e.type, e.payload) for e in events[2:]] == HISTORY
    assert [e.type for e in events[:2]] == [types.SESSION_CREATED, types.SESSION_STATE]
    assert events[1].payload == {"state": "idle", "error": None}
    assert await env.manager.find_by_provider_session(CHAT_A) == session
    assert await env.manager.find_by_provider_session("other") is None


async def test_the_next_message_resumes_the_chat_in_its_folder(env: Env) -> None:
    worktree = env.repo_path.resolve() / ".claude" / "worktrees" / "agent-x"
    git(env.repo_path, "worktree", "add", "-q", "-b", "agent-x", str(worktree))
    commit_file(worktree, "x.txt")
    session = await env.manager.adopt(chat(env, worktree))
    env.provider.script(reply("Again", provider_session_id=CHAT_A))

    await env.manager.send(session.id, "Continue", [])
    await answered(env, session.id)

    (run,) = env.provider.runs
    assert run.spec.resume_id == CHAT_A
    assert run.spec.cwd == worktree
    assert session.base_ref == git(worktree, "rev-parse", "HEAD").strip()


async def test_adopting_needs_the_repo_and_the_chats_folder(env: Env, tmp_path: Path) -> None:
    with pytest.raises(InvalidInputError, match="unknown"):
        await env.manager.adopt(chat(env, repo="nope"))
    with pytest.raises(NoWorkspaceError, match="no longer exists"):
        await env.manager.adopt(chat(env, tmp_path / "gone"))
    shutil.rmtree(env.repo_path)
    with pytest.raises(RepoFolderMissingError):
        await env.manager.adopt(chat(env))
    assert await env.store.list_sessions() == []


async def test_sending_is_refused_while_claude_code_has_the_chat_open(env: Env) -> None:
    session = await env.manager.adopt(chat(env))
    env.claude.open_chat(4242, CHAT_A, entrypoint="claude-desktop")
    env.alive.add(4242)

    with pytest.raises(ChatOpenElsewhereError) as refused:
        await env.manager.send(session.id, "Continue", [])

    assert refused.value.status_code == 409
    assert refused.value.payload() == {
        "detail": "This chat is open in Claude Code right now. Close it there first.",
        "code": "open_in_claude_code",
    }
    assert env.provider.runs == []
    env.alive.clear()  # Claude Code quit, leaving its file behind
    env.provider.script(reply("ok", provider_session_id=CHAT_A))
    await env.manager.send(session.id, "Continue", [])
    await answered(env, session.id)


async def test_nests_own_sdk_run_does_not_count_as_elsewhere(env: Env) -> None:
    env.provider.script(reply("one"), reply("two"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    env.claude.open_chat(77, "sdk-1", entrypoint="sdk-py")
    env.alive.add(77)

    await env.manager.send(created.id, "more", [])
    await env.reach(created.id, SessionState.IDLE)
    # Once Nest let its run go, a live SDK process is someone else's.
    await env.manager.update(created.id, UpdateSession(archived=True))

    with pytest.raises(ChatOpenElsewhereError):
        await env.manager.send(created.id, "again", [])


async def test_sessions_without_an_engine_session_are_never_refused(env: Env) -> None:
    env.provider.script(reply("one"))
    env.claude.open_chat(5, "sdk-1")
    env.alive.add(5)

    created = await env.create(mode="in_place")

    assert created.provider_session_id is None
    await env.reach(created.id, SessionState.IDLE)
