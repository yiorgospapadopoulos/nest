"""A chat outlives its worktree (B119): the chat tool, its timing, safety and state."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.approvals.models import ApprovalKind
from nestd.gitops.runner import GitError
from nestd.providers.base import ForkPoint, ToolRefusedError
from nestd.sessions.models import CreateSession, NewSession, Session, SessionState
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, Turn, background, reply, until_interrupted
from tests.fakes import FakeClock
from tests.git_support import commit_file, git
from tests.session_support import Env

TOOL = "worktree"

type Args = dict[str, JsonValue]


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    environment.use_worktrees()
    yield environment
    await environment.manager.shutdown()


async def call(run: FakeRun, args: Args) -> str:
    tool = next(tool for tool in run.spec.nest_tools if tool.name == TOOL)
    return await tool.handler(args)


def asks(args: Args, then: Turn) -> Turn:
    """The agent calls the chat's worktree tool, then goes on with `then`."""

    async def turn(run: FakeRun) -> None:
        await call(run, args)
        await then(run)

    return turn


def refused(args: Args, seen: list[str]) -> Turn:
    """The agent calls the tool, is refused and ends its turn."""

    async def turn(run: FakeRun) -> None:
        try:
            await call(run, args)
        except ToolRefusedError as error:
            seen.append(str(error))
        await reply("ok")(run)

    return turn


async def worktree_chat(env: Env, title: str = "first") -> Session:
    env.provider.script(reply("ok"))
    created = await env.create(title, mode="worktree")
    session = await env.reach(created.id, SessionState.IDLE)
    assert session.worktree_path is not None
    return session


async def turn_with(env: Env, session: Session, turn: Turn, text: str = "do it") -> Session:
    await env.reach(session.id, (await env.store.get(session.id)).state)
    env.provider.script(turn)
    before = len(await env.states(session.id))
    await env.manager.send(session.id, text, [])

    async def ended() -> bool:
        states = await env.states(session.id)
        return len(states) > before and states[-1] == SessionState.IDLE

    await until(ended)
    return await env.store.get(session.id)


async def next_message_runs_in(env: Env, session: Session) -> Path:
    runs = len(env.provider.runs)
    await turn_with(env, session, reply("here"))
    assert len(env.provider.runs) == runs + 1
    return env.provider.runs[-1].spec.cwd


async def notices(env: Env, session: Session, kind: str) -> list[str]:
    return [
        str(event.payload["text"])
        for event in await env.bus.session_events(session.id)
        if event.type == "session.notice" and event.payload["kind"] == kind
    ]


async def recorded(env: Env, session: Session) -> None:
    async def done() -> bool:
        return (await env.store.get(session.id)).pending_worktree is not None

    await until(done)


async def test_removal_waits_for_the_turn_to_end(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    during: list[bool] = []

    async def goes_on(run: FakeRun) -> None:
        during.append(path.exists() and not run.closed)
        await reply("removing it when this turn ends")(run)

    done = await turn_with(env, session, asks({"action": "remove"}, goes_on))

    assert during == [True]
    assert not path.exists()
    assert (done.mode, done.worktree_path, done.cwd) == ("in_place", None, env.repo_path)
    assert done.branch is None
    assert session.branch is not None
    assert session.branch in git(env.repo_path, "branch", "--list", session.branch)
    assert [(e.path, e.branch, e.state) for e in done.earlier_worktrees] == [
        (path, session.branch, "deleted")
    ]
    events = await env.bus.session_events(session.id)
    workspace = [event for event in events if event.type == "session.workspace"][-1]
    assert workspace.payload["path"] == str(env.repo_path)
    assert (workspace.payload["mode"], workspace.payload["branch"]) == ("in_place", None)
    assert workspace.payload["worktree_path"] is None
    assert workspace.payload["earlier_worktrees"] == [
        entry.model_dump(mode="json") for entry in done.earlier_worktrees
    ]
    updated = [event for event in events if event.type == "session.updated"][-1]
    assert (updated.id or 0) > (workspace.id or 0)


async def test_removal_waits_for_background_agents_then_applies(env: Env) -> None:
    """B127: the engine runs a called pixie as a background agent by default, so Closer
    asks to remove the worktree while its own background task runs.
    """
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    answer: list[str] = []

    async def asks_from_the_background(run: FakeRun) -> None:
        await background(1)(run)
        answer.append(await call(run, {"action": "remove"}))
        await reply("Closer works on")(run)

    during = await turn_with(env, session, asks_from_the_background)

    assert "Recorded" in answer[0]
    assert path.exists()
    assert during.pending_worktree is not None
    assert during.worktree_path == path

    await background(0)(env.provider.runs[-1])
    await until(lambda: not env.manager.background_running(session.id))
    done = await turn_with(env, session, reply("Closer finished"))

    assert not path.exists()
    assert done.pending_worktree is None
    assert (done.mode, done.worktree_path) == ("in_place", None)


async def test_the_next_message_resumes_in_the_project_folder_without_a_new_worktree(
    env: Env,
) -> None:
    session = await worktree_chat(env)
    await turn_with(env, session, asks({"action": "remove"}, reply("ok")))

    assert await next_message_runs_in(env, session) == env.repo_path

    run = env.provider.runs[-1]
    assert run.spec.resume_id == "sdk-1"
    assert run.spec.system_prompt_append is not None
    assert str(env.repo_path) in run.spec.system_prompt_append
    # An ACP engine takes no prompt when it resumes, so the message says it too.
    assert str(env.repo_path) in run.inputs[-1].text
    assert not list((env.repo_path / ".claude" / "worktrees").glob("nest-*"))


async def test_a_message_queued_meanwhile_starts_in_the_new_folder(env: Env) -> None:
    session = await worktree_chat(env)
    release = asyncio.Event()

    async def waits(run: FakeRun) -> None:
        await release.wait()
        await reply("removing")(run)

    env.provider.script(asks({"action": "remove"}, waits), reply("queued one"))
    await env.manager.send(session.id, "remove it", [])
    await recorded(env, session)
    env.provider.runs[-1].steers = False
    queued = await env.manager.send(session.id, "then this", [])
    assert queued.queued_message is not None

    release.set()

    async def resumed() -> bool:
        return len(env.provider.runs) == 2 and bool(env.provider.runs[-1].inputs)

    await until(resumed)
    assert env.provider.runs[-1].spec.cwd == env.repo_path
    assert env.provider.runs[-1].inputs[-1].text.endswith("then this")


async def test_a_message_that_cuts_the_turn_short_starts_in_the_new_folder(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    env.provider.script(asks({"action": "remove"}, until_interrupted()), reply("next"))
    await env.manager.send(session.id, "remove it", [])
    await recorded(env, session)

    await env.manager.send(session.id, "this now", [], interrupt=True)

    async def resumed() -> bool:
        return len(env.provider.runs) == 2 and bool(env.provider.runs[-1].inputs)

    await until(resumed)
    assert not path.exists()
    assert env.provider.runs[-1].spec.cwd == env.repo_path
    assert env.provider.runs[-1].inputs[-1].text.endswith("this now")


async def test_a_stop_cancels_the_change_and_the_agent_hears_so(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    env.provider.script(asks({"action": "remove"}, until_interrupted()))
    await env.manager.send(session.id, "remove it", [])
    await recorded(env, session)

    await env.manager.interrupt(session.id)
    stopped = await env.reach(session.id, SessionState.INTERRUPTED)

    assert path.exists()
    assert stopped.worktree_path == path
    assert stopped.pending_worktree is None
    assert await notices(env, session, "worktree_failed")
    await turn_with(env, session, reply("ok"), "go on")
    assert "did not happen" in env.provider.runs[-1].inputs[-1].text


async def test_a_restart_applies_the_recorded_change(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    env.provider.script(asks({"action": "remove"}, until_interrupted()))
    await env.manager.send(session.id, "remove it", [])
    await recorded(env, session)
    await env.manager.shutdown()
    assert path.exists()

    env.manager = env.build(timedelta(hours=1))
    await env.manager.recover()

    async def applied() -> bool:
        return (await env.store.get(session.id)).pending_worktree is None

    await until(applied)
    assert not path.exists()
    assert (await env.store.get(session.id)).worktree_path is None


async def test_a_failed_removal_leaves_the_chat_usable_and_says_what_failed(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None

    async def fails(*_: object) -> bool:
        raise GitError(["worktree", "remove"], 1, "it is locked")

    monkeypatch.setattr(env.worktrees, "remove", fails)
    done = await turn_with(env, session, asks({"action": "remove"}, reply("ok")))

    assert done.worktree_path == path
    assert done.pending_worktree is None
    assert done.earlier_worktrees == []
    assert any("it is locked" in text for text in await notices(env, session, "worktree_failed"))
    assert await next_message_runs_in(env, session) == path
    assert "did not happen" in env.provider.runs[-1].inputs[-1].text


async def test_a_new_worktree_becomes_current_and_the_earlier_one_stays(env: Env) -> None:
    session = await worktree_chat(env)
    first = session.worktree_path
    assert first is not None

    done = await turn_with(env, session, asks({"action": "new"}, reply("ok")))

    assert done.worktree_path not in (None, first)
    assert done.mode == "worktree"
    assert done.branch != session.branch
    assert done.cwd == done.worktree_path
    assert first.exists()
    assert [(e.path, e.state) for e in done.earlier_worktrees] == [(first, "kept")]
    assert await next_message_runs_in(env, session) == done.worktree_path

    back = await turn_with(
        env, session, asks({"action": "back", "worktree": str(first)}, reply("ok"))
    )

    assert (back.worktree_path, back.branch) == (first, session.branch)
    assert [(e.path, e.state) for e in back.earlier_worktrees] == [(done.worktree_path, "kept")]


async def test_a_new_worktree_starts_from_the_base_asked_for(env: Env) -> None:
    session = await worktree_chat(env)
    git(env.repo_path, "branch", "feature")
    commit_file(env.repo_path, "later.txt", "x")

    done = await turn_with(
        env, session, asks({"action": "new", "base": "feature", "branch": "next"}, reply("ok"))
    )

    assert done.branch == "next"
    assert done.worktree_path is not None
    assert not (done.worktree_path / "later.txt").exists()


async def test_removal_then_new_in_one_turn_applies_both(env: Env) -> None:
    session = await worktree_chat(env)
    first = session.worktree_path
    assert first is not None

    done = await turn_with(
        env, session, asks({"action": "remove"}, asks({"action": "new"}, reply("ok")))
    )

    assert not first.exists()
    assert done.mode == "worktree"
    assert done.worktree_path != first
    assert [(e.path, e.state) for e in done.earlier_worktrees] == [(first, "deleted")]


async def test_a_worktree_another_open_chat_uses_stays(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None
    env.provider.script(reply("joined"))
    joined = await env.create("second", worktree_path=str(path))
    await env.reach(joined.id, SessionState.IDLE)
    seen: list[str] = []

    done = await turn_with(env, session, refused({"action": "remove"}, seen))

    assert seen
    assert "another" in seen[0].lower()
    assert path.exists()
    assert done.worktree_path == path


async def test_only_worktrees_nest_made_are_removed(env: Env) -> None:
    session = await worktree_chat(env)
    theirs = env.repo_path / ".claude" / "worktrees" / "their-own"
    git(env.repo_path, "worktree", "add", "-q", "-b", "theirs", str(theirs))
    seen: list[str] = []

    await turn_with(env, session, refused({"action": "remove", "worktree": "their-own"}, seen))

    assert seen
    assert theirs.exists()


async def test_deleting_a_chat_keeps_its_worktree_for_any_chat_to_remove(env: Env) -> None:
    gone = await worktree_chat(env, "gone")
    path = gone.worktree_path
    assert path is not None
    await env.manager.purge(gone.id)
    assert path.exists()

    other = await worktree_chat(env, "other")
    listed: list[str] = []

    async def lists(run: FakeRun) -> None:
        listed.append(await call(run, {"action": "list"}))
        await call(run, {"action": "remove", "worktree": path.name})
        await reply("ok")(run)

    done = await turn_with(env, other, lists)

    assert path.name in listed[0]
    assert not path.exists()
    assert done.worktree_path == other.worktree_path


async def test_removing_a_worktree_marks_it_deleted_in_every_chat_that_kept_it(env: Env) -> None:
    first = await worktree_chat(env, "first")
    path = first.worktree_path
    assert path is not None
    await turn_with(env, first, asks({"action": "new"}, reply("ok")))
    other = await worktree_chat(env, "other")

    await turn_with(env, other, asks({"action": "remove", "worktree": str(path)}, reply("ok")))

    moved = await env.store.get(first.id)
    assert [(e.path, e.state) for e in moved.earlier_worktrees] == [(path, "deleted")]


async def test_only_new_chats_are_marked_and_old_ones_get_no_tool(env: Env) -> None:
    session = await worktree_chat(env)
    assert session.movable is True
    old = await env.store.update(session.id, movable=False)
    await env.manager.close_idle_run(old.id)

    await turn_with(env, old, reply("still ok"))

    assert not [tool for tool in env.provider.runs[-1].spec.nest_tools if tool.name == TOOL]


async def test_chats_a_pixie_started_are_never_marked(env: Env) -> None:
    env.provider.script(reply("ok"))
    request = CreateSession.model_validate({"repo": "repo", "prompt": "work", "mode": "worktree"})

    session = await env.manager.create(request, started_by_pixie="p1")
    idle = await env.reach(session.id, SessionState.IDLE)

    assert idle.movable is False
    assert not [tool for tool in env.provider.runs[-1].spec.nest_tools if tool.name == TOOL]
    await env.manager.purge(idle.id)
    assert idle.worktree_path is not None
    assert not idle.worktree_path.exists()


async def test_deleting_an_unmarked_chat_still_removes_its_worktree(env: Env) -> None:
    session = await worktree_chat(env)
    await env.store.update(session.id, movable=False)

    await env.manager.purge(session.id)

    assert session.worktree_path is not None
    assert not session.worktree_path.exists()


async def test_the_engine_transcript_is_found_after_a_move(env: Env) -> None:
    """Claude Code leaves the transcript under the chat's first folder."""
    session = await worktree_chat(env)
    done = await turn_with(env, session, asks({"action": "new"}, reply("ok")))
    message = next(
        event
        for event in await env.bus.session_events(session.id)
        if event.type == "session.user_message"
    )
    assert message.id is not None
    await env.store.save_checkpoint(session.id, message.id, "cp-1")
    searched: list[Path] = []

    async def only_in_the_project(cwd: Path, _session: str, _message: str) -> ForkPoint | None:
        searched.append(cwd)
        return ForkPoint("entry") if cwd == env.repo_path else None

    env.provider.fork_point = only_in_the_project  # type: ignore[method-assign]

    preview = await env.manager.rewind(session.id, message.id, dry_run=True, restore="conversation")

    assert preview.can_rewind is True
    assert searched == [done.cwd, env.repo_path]


async def test_files_cannot_be_restored_to_before_a_move(env: Env, clock: FakeClock) -> None:
    session = await worktree_chat(env)
    message = next(
        event
        for event in await env.bus.session_events(session.id)
        if event.type == "session.user_message"
    )
    assert message.id is not None
    await env.store.save_checkpoint(session.id, message.id, "cp-1")
    clock.advance(timedelta(minutes=1))
    await turn_with(env, session, asks({"action": "remove"}, reply("ok")))

    preview = await env.manager.rewind(session.id, message.id, dry_run=True, restore="code")

    assert preview.can_rewind is False
    assert preview.error is not None
    assert "moved" in preview.error


async def test_the_change_can_be_taken_back_in_the_same_turn(env: Env) -> None:
    session = await worktree_chat(env)
    path = session.worktree_path
    assert path is not None

    done = await turn_with(
        env, session, asks({"action": "remove"}, asks({"action": "cancel"}, reply("ok")))
    )

    assert path.exists()
    assert done.worktree_path == path


async def test_a_merged_branch_goes_with_its_worktree(env: Env) -> None:
    session = await worktree_chat(env)
    assert session.branch is not None
    assert session.worktree_path is not None

    await turn_with(env, session, asks({"action": "remove", "delete_branch": True}, reply("ok")))

    assert not session.worktree_path.exists()
    assert git(env.repo_path, "branch", "--list", session.branch) == ""
    assert await notices(env, session, "worktree_changed") == [
        f"Worktree {session.worktree_path.name} removed with its branch {session.branch}."
    ]


async def test_an_unmerged_branch_survives_and_its_worktree_still_goes(env: Env) -> None:
    session = await worktree_chat(env)
    assert session.branch is not None
    assert session.worktree_path is not None
    commit_file(session.worktree_path, "work.txt", "unmerged")

    async def allow() -> None:
        async def asked() -> bool:
            return await env.approvals.pending(session.id, ApprovalKind.PERMISSION) is not None

        await until(asked)
        item = await env.approvals.pending(session.id, ApprovalKind.PERMISSION)
        assert item is not None
        await env.approvals.resolve(item.id, {"behavior": "allow"})

    # The unmerged commit is work: the user says yes to losing the worktree (B141).
    answer = asyncio.create_task(allow())
    done = await turn_with(
        env, session, asks({"action": "remove", "delete_branch": True}, reply("ok"))
    )
    await answer

    assert not session.worktree_path.exists()
    assert session.branch in git(env.repo_path, "branch", "--list", session.branch)
    assert done.worktree_path is None
    assert await notices(env, session, "worktree_failed") == []
    assert await notices(env, session, "worktree_changed") == [
        f"Worktree {session.worktree_path.name} removed."
        f" Its branch {session.branch} stays: not merged into main."
    ]


async def test_removal_keeps_a_merged_branch_unless_asked(env: Env) -> None:
    session = await worktree_chat(env)
    assert session.branch is not None

    await turn_with(env, session, asks({"action": "remove"}, reply("ok")))

    assert session.branch in git(env.repo_path, "branch", "--list", session.branch)


@pytest.mark.parametrize("branch", ["main", "feature"])
async def test_the_default_and_the_checked_out_branch_are_never_deleted(
    env: Env, branch: str
) -> None:
    git(env.repo_path, "checkout", "-q", "-b", "feature")
    repo = env.repos.get("repo")
    assert repo.default_branch == "main"

    stays = await env.worktrees.delete_branch(repo, branch)

    assert stays is not None
    assert branch in git(env.repo_path, "branch", "--list", branch)


async def test_a_called_pixies_folder_follows_its_caller(env: Env) -> None:
    session = await worktree_chat(env)
    called = await env.store.create(
        NewSession(
            repo="repo",
            title="called",
            prompt="work",
            mode="in_place",
            cwd=session.cwd,
            model=None,
            effort=None,
            permission_mode="default",
            provider="claude",
            called_by=session.id,
        )
    )

    await turn_with(env, session, asks({"action": "remove"}, reply("ok")))

    assert (await env.store.get(called.id)).cwd == env.repo_path


def moves_itself(folder: Path, then: Turn, *, removed: bool = False) -> Turn:
    """The agent changes folder with the engine's own tool, which Nest does not run."""

    async def turn(run: FakeRun) -> None:
        await run.sink.folder_changed(folder, removed=removed)
        await then(run)

    return turn


def agents_worktree(env: Env) -> Path:
    """A worktree the engine made, as `EnterWorktree` does."""
    folder = env.repo_path / ".claude" / "worktrees" / "own"
    git(env.repo_path, "worktree", "add", "-q", "-b", "own-branch", str(folder))
    return folder


async def in_place_chat(env: Env, *, movable: bool = True) -> Session:
    env.provider.script(reply("ok"))
    created = await env.create("in place", mode="in_place")
    session = await env.reach(created.id, SessionState.IDLE)
    if not movable:
        session = await env.store.update(session.id, movable=False)
    return session


@pytest.mark.parametrize("movable", [True, False])
async def test_a_chat_follows_its_agent_into_a_worktree_it_made_itself(
    env: Env, *, movable: bool
) -> None:
    session = await in_place_chat(env, movable=movable)
    folder = agents_worktree(env).resolve()

    moved = await turn_with(env, session, moves_itself(folder, reply("ok")))

    assert (moved.mode, moved.branch) == ("worktree", "own-branch")
    assert (moved.cwd, moved.worktree_path) == (folder, folder)
    assert await next_message_runs_in(env, moved) == folder


async def test_a_chat_follows_its_agent_back_and_keeps_the_worktree_as_earlier(env: Env) -> None:
    session = await in_place_chat(env)
    folder = agents_worktree(env).resolve()
    await turn_with(env, session, moves_itself(folder, reply("ok")))

    back = await turn_with(env, session, moves_itself(env.repo_path, reply("ok")))

    assert (back.mode, back.worktree_path, back.cwd) == ("in_place", None, env.repo_path)
    assert [(e.path, e.branch, e.state) for e in back.earlier_worktrees] == [
        (folder, "own-branch", "kept")
    ]


async def test_a_worktree_the_agent_removed_itself_shows_deleted(env: Env) -> None:
    session = await in_place_chat(env)
    folder = agents_worktree(env).resolve()
    await turn_with(env, session, moves_itself(folder, reply("ok")))

    back = await turn_with(env, session, moves_itself(env.repo_path, reply("ok"), removed=True))

    assert [e.state for e in back.earlier_worktrees] == ["deleted"]


async def test_a_folder_outside_the_project_leaves_the_chat_where_it_is(
    env: Env, tmp_path: Path
) -> None:
    session = await in_place_chat(env)
    stranger = tmp_path / "elsewhere"
    stranger.mkdir()

    after = await turn_with(env, session, moves_itself(stranger, reply("ok")))

    assert (after.state, after.mode, after.cwd) == (SessionState.IDLE, "in_place", session.cwd)
