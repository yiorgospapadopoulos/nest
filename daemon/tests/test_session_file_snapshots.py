"""B145: a chat's files come back from Nest's git snapshot of each message, on any engine."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.events import types
from nestd.gitops import snapshots
from nestd.gitops.runner import GitError
from nestd.providers.base import ForkPoint
from nestd.repos.service import GENERAL
from nestd.sessions.checkpoints import FileCheckpoints
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from tests.fake_provider import RESULT, FakeRun, background, echoed, edit, reply
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
    # The engine reports no checkpoint of its own, as Codex and ACP engines do not. What
    # the first turn changed, by any tool or command.
    env.provider.script(
        edit({"README.md": "edited\n", "made.txt": "new\n"}, reply("one")), reply("two")
    )
    repo = env.repo_path
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
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
    env.provider.script(
        edit({"README.md": "the fork's work\n"}, reply("go", provider_session_id="sdk-7"))
    )
    await env.manager.send(fork.session.id, "go on", [])
    await until_results(env, fork.session.id, 2)
    original = (await env.store.get(source.id)).worktree_path
    own = (await env.store.get(fork.session.id)).worktree_path
    assert original is not None
    assert own is not None
    (original / "README.md").write_text("the original's work\n", encoding="utf-8")
    assert (own / "README.md").read_text(encoding="utf-8") == "the fork's work\n"
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


async def test_an_undo_leaves_what_others_changed_between_the_chats_turns(env: Env) -> None:
    """B159 R10: an in-place chat shares the checkout with the user and other chats; its
    undo restores only the files its own turns changed, and its preview says the same.
    """
    repo = env.repo_path
    env.provider.script(
        edit({"README.md": "the chat's edit\n", "mine.txt": "new\n"}, reply("one")),
        reply("two"),
    )
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    # Between the chat's turns: another chat or the user makes and edits files.
    (repo / "theirs.txt").write_text("another chat's file\n", encoding="utf-8")
    (repo / "notes.md").write_text("the user's notes\n", encoding="utf-8")
    await env.manager.send(created.id, "and more", [])
    await until_results(env, created.id, 2)
    first, _ = await user_messages(env, created.id)

    preview = await env.manager.rewind(created.id, first, dry_run=True)
    restored = await env.manager.rewind(created.id, first, dry_run=False)

    assert sorted(preview.files_changed) == ["README.md", "mine.txt"]
    assert sorted(restored.files_changed) == sorted(preview.files_changed)
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert not (repo / "mine.txt").exists()
    assert (repo / "theirs.txt").read_text(encoding="utf-8") == "another chat's file\n"
    assert (repo / "notes.md").read_text(encoding="utf-8") == "the user's notes\n"


async def test_a_turn_cut_off_by_a_restart_still_undoes_only_its_own_files(env: Env) -> None:
    """B159 R10: the turn's start was kept only in memory, so after a restart its
    checkpoint had no paths, and an undo put back the whole folder.
    """
    repo = env.repo_path
    env.provider.script(reply("one"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (first,) = await user_messages(env, created.id)
    # The next turn starts and edits a file, then the daemon is killed mid-turn.
    await FileCheckpoints(env.store).take(created.id, first, repo)
    (repo / "README.md").write_text("the cut-off turn's edit\n", encoding="utf-8")

    restarted = env.build(timedelta(hours=1))
    await restarted.recover()
    (repo / "notes.md").write_text("the user's notes, after the restart\n", encoding="utf-8")
    restored = await FileCheckpoints(env.store).restore(created.id, first, repo, dry_run=False)
    await restarted.shutdown()

    assert restored.files_changed == [str(repo.resolve() / "README.md")]
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (repo / "notes.md").exists()


async def fixes_after_the_build(run: FakeRun) -> None:
    """A turn the agent starts on its own once its background build is done."""
    await run.sink.text_delta("the build finished")
    (run.spec.cwd / "README.md").write_text("fixed after the build\n", encoding="utf-8")
    await run.sink.result(RESULT)


async def test_an_undo_takes_back_a_turn_the_agent_started_on_its_own(env: Env) -> None:
    repo = env.repo_path
    env.provider.script(background(1, reply("started a build")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (repo / "theirs.txt").write_text("another chat's file\n", encoding="utf-8")
    env.provider.runs[0].emit(background(0, fixes_after_the_build))
    await until_results(env, created.id, 2)
    (first,) = await user_messages(env, created.id)

    restored = await env.manager.rewind(created.id, first, dry_run=False)

    assert restored.files_changed == ["README.md"]
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"
    assert (repo / "theirs.txt").exists()


async def test_a_general_chat_inside_a_git_home_folder_takes_no_checkpoint(
    env: Env, tmp_path: Path
) -> None:
    """B159 R10: the home folder kept in git must not be snapshotted, nor its files undone."""
    home = tmp_path
    git(home, "init", "-q")
    (home / ".zshrc").write_text("export A=1\n", encoding="utf-8")
    git(home, "add", ".zshrc")
    git(home, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "dotfiles")
    env.provider.script(reply("one"), reply("two"))
    created = await env.create(repo=GENERAL)
    await env.reach(created.id, SessionState.IDLE)
    (home / "Documents").mkdir()
    (home / "Documents" / "thesis.txt").write_text("chapter one\n", encoding="utf-8")
    (home / ".zshrc").write_text("export A=2\n", encoding="utf-8")
    await env.manager.send(created.id, "and more", [])
    await until_results(env, created.id, 2)
    first, _ = await user_messages(env, created.id)

    preview = await env.manager.rewind(created.id, first, dry_run=True)

    assert not preview.can_rewind
    assert git(home, "for-each-ref", "refs/nest/") == ""
    assert (home / "Documents" / "thesis.txt").exists()
    assert (home / ".zshrc").read_text(encoding="utf-8") == "export A=2\n"


async def _git_fails(*args: object, **kwargs: object) -> object:
    raise GitError(["status"], 128, "fatal: unable to read the index")


@pytest.mark.parametrize("failing", ["snapshot", "state", "changed_since"])
async def test_an_unmeasured_turn_makes_an_undo_restore_the_whole_folder(
    env: Env, monkeypatch: pytest.MonkeyPatch, failing: str
) -> None:
    """B159 R10: git failing on a new message's snapshot, at the start of a turn the agent
    began on its own, or when a turn's changes are recorded must not leave a list of paths
    that looks complete but misses that turn's files.
    """
    repo = env.repo_path
    env.provider.script(reply("one"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (first,) = await user_messages(env, created.id)
    checkpoints = FileCheckpoints(env.store)
    if failing == "changed_since":
        await checkpoints.turn_started(created.id, repo)
    monkeypatch.setattr(snapshots, failing, _git_fails)
    # The turn that goes unmeasured edits a file.
    (repo / "README.md").write_text("the unmeasured turn's edit\n", encoding="utf-8")
    if failing == "snapshot":
        await checkpoints.take(created.id, first + 1000, repo)
    elif failing == "state":
        await checkpoints.turn_started(created.id, repo)
    else:
        await checkpoints.turn_ended(created.id)
    monkeypatch.undo()

    restored = await checkpoints.restore(created.id, first, repo, dry_run=False)

    assert restored.files_changed == [str(repo.resolve() / "README.md")]
    assert (repo / "README.md").read_text(encoding="utf-8") == "hello\n"
