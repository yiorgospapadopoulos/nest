"""Prepare a session's worktree: create, link, set up, and report each step as events."""

import asyncio

from harness.config.models import RepoConfig
from harness.events import types
from harness.events.bus import EventBus
from harness.sessions.models import Session
from harness.sessions.store import SessionStore
from harness.worktrees.manager import Worktree, WorktreeManager
from harness.worktrees.setup import SetupResult


async def prepare_worktree(
    session: Session,
    repo: RepoConfig,
    worktrees: WorktreeManager,
    store: SessionStore,
    bus: EventBus,
) -> SetupResult:
    # git finishes adding a worktree even when the session is interrupted meanwhile, so the
    # new worktree is always recorded: closing or deleting the session then removes it,
    # and the next message works in it (D048). Setup commands stay interruptible.
    worktree = await _uninterrupted(
        asyncio.ensure_future(_create(session, repo, worktrees, store, bus))
    )
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
) -> Worktree:
    worktree = await worktrees.create(repo, session.id, session.title)
    await store.update(
        session.id,
        cwd=worktree.path,
        worktree_path=worktree.path,
        branch=worktree.branch,
        base_ref=worktree.base_ref,
    )
    links = worktrees.link(repo, worktree.path)
    await bus.publish(
        types.SESSION_WORKSPACE,
        {
            "path": str(worktree.path),
            "branch": worktree.branch,
            "base_ref": worktree.base_ref,
            "linked": [*links.linked],
            "missing": [*links.missing],
            "existing": [*links.existing],
        },
        session.id,
    )
    return worktree


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
