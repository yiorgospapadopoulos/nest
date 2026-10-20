"""Prepare a session's worktree: create, link, set up, and report each step as events."""

import asyncio

from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import GitError
from nestd.sessions.joining import linked_checkout
from nestd.sessions.models import Session
from nestd.sessions.store import SessionStore
from nestd.worktrees.manager import Worktree, WorktreeManager
from nestd.worktrees.setup import LinkResult, SetupResult


async def prepare_worktree(
    session: Session,
    repo: RepoConfig,
    worktrees: WorktreeManager,
    store: SessionStore,
    bus: EventBus,
) -> SetupResult | None:
    """None when the chat joined a worktree made for its branch meanwhile: it has nothing
    to set up.
    """
    # git finishes adding a worktree even when the session is interrupted meanwhile, so the
    # new worktree is always recorded: closing or deleting the session then removes it,
    # and the next message works in it (D048). Setup commands stay interruptible.
    worktree = await _uninterrupted(
        asyncio.ensure_future(_create(session, repo, worktrees, store, bus))
    )
    if worktree is None:
        return None
    setup = await worktrees.run_setup(repo, worktree.path, session.id)
    if not setup.ok:
        await bus.publish(
            types.SESSION_SETUP_FAILED,
            {
                "command": setup.command,
                "exit_code": setup.exit_code,
                "timed_out": setup.timed_out,
                "log_path": str(setup.log_path),
            },
            session.id,
        )
    return setup


async def _create(
    session: Session,
    repo: RepoConfig,
    worktrees: WorktreeManager,
    store: SessionStore,
    bus: EventBus,
) -> Worktree | None:
    """The new worktree; None when the chat joined one instead. A branch that exists is
    one the chat works on itself (B96), checked out; a branch asked for (B55) is new.
    """
    if session.branch is not None and await worktrees.has_branch(repo, session.branch):
        return await _check_out(session, repo, worktrees, store, bus)
    # A branch name and base asked for are recorded when the session is created (B55).
    worktree = await worktrees.create(
        repo, session.id, session.title, session.branch, session.base_ref
    )
    await _made(session, repo, worktree, worktrees, store, bus)
    return worktree


async def _check_out(
    session: Session,
    repo: RepoConfig,
    worktrees: WorktreeManager,
    store: SessionStore,
    bus: EventBus,
) -> Worktree | None:
    """A chat on an existing branch (B96) gets a worktree with it checked out, or joins
    the worktree that has it checked out by now, such as another chat's on that branch.
    """
    assert session.branch is not None  # noqa: S101 (recorded when the chat was created)
    assert session.base_ref is not None  # noqa: S101
    try:
        worktree = await worktrees.check_out(repo, session.id, session.branch, session.base_ref)
    except GitError:
        found = await linked_checkout(repo, session.branch)
        if found is None:
            raise
        await store.update(session.id, cwd=found, worktree_path=found)
        await publish_workspace(
            bus, session.id, Worktree(found, session.branch, session.base_ref), LinkResult()
        )
        return None
    await _made(session, repo, worktree, worktrees, store, bus)
    return worktree


async def _made(
    session: Session,
    repo: RepoConfig,
    worktree: Worktree,
    worktrees: WorktreeManager,
    store: SessionStore,
    bus: EventBus,
) -> None:
    """Record the session's new worktree, link files into it and announce it."""
    await store.update(
        session.id,
        cwd=worktree.path,
        worktree_path=worktree.path,
        branch=worktree.branch,
        base_ref=worktree.base_ref,
    )
    await publish_workspace(bus, session.id, worktree, worktrees.link(repo, worktree.path))


async def publish_workspace(
    bus: EventBus, session_id: str, worktree: Worktree, links: LinkResult
) -> None:
    """Where the session works now, and what was linked into its worktree."""
    await bus.publish(
        types.SESSION_WORKSPACE,
        {
            "path": str(worktree.path),
            "branch": worktree.branch,
            "base_ref": worktree.base_ref,
            "linked": [*links.linked],
            "missing": [*links.missing],
            "existing": [*links.existing],
            "failed": [*links.failed],
        },
        session_id,
    )


async def _uninterrupted[T](task: asyncio.Future[T]) -> T:
    """`task`'s result, waiting for it even when cancelled meanwhile (any number of times).
    Its own error comes first; otherwise a cancellation is raised once it is done.
    """
    cancelled = False
    while not task.done():
        try:
            await asyncio.wait([task])
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result
