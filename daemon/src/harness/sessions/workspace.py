"""Prepare a session's worktree: create, link, set up, and report each step as events."""

from harness.config.models import RepoConfig
from harness.events import types
from harness.events.bus import EventBus
from harness.sessions.models import Session
from harness.sessions.store import SessionStore
from harness.worktrees.manager import WorktreeManager
from harness.worktrees.setup import SetupResult


async def prepare_worktree(
    session: Session,
    repo: RepoConfig,
    worktrees: WorktreeManager,
    store: SessionStore,
    bus: EventBus,
) -> SetupResult:
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
