"""Nest asks before it removes a worktree that holds work, and keeps it on a no (B141)."""

from collections.abc import AsyncIterator, Callable
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.approvals.models import Approval, ApprovalKind
from nestd.approvals.resolutions import ResolveApproval, resolution_for
from nestd.errors import InvalidInputError
from nestd.providers.base import ToolRefusedError
from nestd.sessions.models import Session, SessionState
from nestd.storage.db import Database
from nestd.worktrees.manager import Worktree
from tests.async_support import until
from tests.fake_provider import FakeRun, Turn, reply
from tests.fakes import FakeClock
from tests.git_support import commit_file, git
from tests.session_support import Env

type Args = dict[str, JsonValue]
type Work = Callable[[Path], object]


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    environment.use_worktrees()
    yield environment
    await environment.manager.shutdown()


async def worktree_chat(env: Env, **fields: object) -> Session:
    env.provider.script(reply("ok"))
    created = await env.create("first", mode="worktree", **fields)
    session = await env.reach(created.id, SessionState.IDLE)
    assert session.worktree_path is not None
    return session


def removing(seen: list[str], then: Work | None = None) -> Turn:
    """The agent asks to remove the chat's worktree, notes the answer, may change the
    worktree with `then`, and ends its turn.
    """

    async def turn(run: FakeRun) -> None:
        tool = next(tool for tool in run.spec.nest_tools if tool.name == "worktree")
        try:
            seen.append(await tool.handler({"action": "remove"}))
        except ToolRefusedError as error:
            seen.append(f"refused: {error}")
        if then is not None:
            then(run.spec.cwd)
        await reply("ok")(run)

    return turn


async def start_turn(env: Env, session: Session, turn: Turn) -> int:
    env.provider.script(turn)
    before = len(await env.states(session.id))
    await env.manager.send(session.id, "remove it", [])
    return before


async def turn_ended(env: Env, session: Session, before: int) -> Session:
    async def ended() -> bool:
        states = await env.states(session.id)
        return len(states) > before and states[-1] == SessionState.IDLE

    await until(ended)
    return await env.store.get(session.id)


async def card(env: Env, session: Session) -> Approval:
    found: list[Approval] = []

    async def asked() -> bool:
        item = await env.approvals.pending(session.id, ApprovalKind.PERMISSION)
        found[:] = [] if item is None else [item]
        return item is not None

    await until(asked)
    return found[0]


def edit_readme(path: Path) -> None:
    (path / "README.md").write_text("changed\n", encoding="utf-8")


def add_untracked(path: Path) -> None:
    (path / "notes.txt").write_text("mine\n", encoding="utf-8")


def add_commit(path: Path) -> None:
    commit_file(path, "work.txt", "unmerged")


@pytest.mark.parametrize(
    ("work", "named"),
    [
        (edit_readme, "README.md"),
        (add_untracked, "notes.txt"),
        (add_commit, "add work.txt"),
    ],
)
async def test_a_worktree_with_work_is_kept_on_a_no(env: Env, work: Work, named: str) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    work(path)
    files = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    seen: list[str] = []

    before = await start_turn(env, session, removing(seen))
    item = await card(env, session)
    await env.approvals.resolve(item.id, {"behavior": "deny"})
    done = await turn_ended(env, session, before)

    assert named in str(item.payload["reason"])
    assert str(item.payload["title"]).startswith(f"Remove the worktree {path.name}? It has ")
    assert item.payload["always"] is False
    assert seen[0].startswith(f"refused: The user kept the worktree {path}")
    assert done.worktree_path == path
    assert done.pending_worktree is None
    assert {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()} == files


async def test_a_yes_removes_the_worktree_and_keeps_its_branch(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    add_commit(path)
    seen: list[str] = []

    before = await start_turn(env, session, removing(seen))
    item = await card(env, session)
    await env.approvals.resolve(item.id, {"behavior": "allow"})
    done = await turn_ended(env, session, before)

    assert seen[0].startswith("Recorded.")
    assert not path.exists()
    assert done.worktree_path is None
    assert str(session.branch) in git(env.repo_path, "branch", "--list", str(session.branch))


async def test_a_clean_worktree_goes_without_asking(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    seen: list[str] = []

    before = await start_turn(env, session, removing(seen))
    await turn_ended(env, session, before)

    assert not path.exists()
    assert await env.approvals.list_approvals() == []


async def test_work_added_after_the_yes_keeps_the_worktree(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    add_untracked(path)
    seen: list[str] = []

    before = await start_turn(env, session, removing(seen, then=edit_readme))
    item = await card(env, session)
    await env.approvals.resolve(item.id, {"behavior": "allow"})
    done = await turn_ended(env, session, before)

    assert path.is_dir()
    assert (path / "README.md").read_text(encoding="utf-8") == "changed\n"
    assert done.worktree_path == path
    assert done.worktree_note is not None
    assert "more than the user agreed to lose" in done.worktree_note


async def test_bypass_mode_still_asks(env: Env) -> None:
    session = await worktree_chat(env, permission_mode="bypassPermissions")
    path = session.worktree_path
    assert path is not None
    add_untracked(path)
    seen: list[str] = []

    before = await start_turn(env, session, removing(seen))
    item = await card(env, session)
    await env.approvals.resolve(item.id, {"behavior": "deny"})
    await turn_ended(env, session, before)

    assert path.is_dir()


async def test_the_card_cannot_be_allowed_always(env: Env) -> None:
    session = await worktree_chat(env)
    item = await env.approvals.add(
        session.id, ApprovalKind.PERMISSION, {"tool": "worktree", "always": False}, "Remove?"
    )

    with pytest.raises(InvalidInputError):
        resolution_for(item, ResolveApproval(behavior="allow", always=True))


async def test_deleting_a_chat_keeps_its_worktree_with_work(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    await env.store.update(session.id, movable=False)
    add_untracked(path)

    await env.manager.purge(session.id)

    assert (path / "notes.txt").read_text(encoding="utf-8") == "mine\n"


async def test_a_merged_chat_keeps_its_worktree_with_uncommitted_files(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    await env.store.update(session.id, movable=False)
    edit_readme(path)

    await env.manager.close(session.id, remove_worktree=True)

    assert (path / "README.md").read_text(encoding="utf-8") == "changed\n"


async def test_the_check_names_changed_untracked_and_unmerged_work(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    repo = env.repos.get("repo")
    worktree = Worktree(path, str(session.branch), str(session.base_ref))
    assert (await env.worktrees.at_risk(repo, worktree)).empty

    add_commit(path)
    git(path, "mv", "README.md", "READ.md")
    add_untracked(path)
    risk = await env.worktrees.at_risk(repo, worktree)

    assert risk.changed == ("READ.md",)
    assert risk.untracked == ("notes.txt",)
    assert [commit.subject for commit in risk.commits] == ["add work.txt"]
    assert risk.summary() == "1 uncommitted file, 1 untracked file and 1 commit not on main"
