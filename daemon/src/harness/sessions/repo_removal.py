"""Unregister a repo, optionally purging its sessions first; its folder is never touched."""

from harness.events import types
from harness.events.bus import EventBus
from harness.repos.service import RepoInUseError, RepoService
from harness.sessions.manager import SessionManager


async def remove_repo(
    name: str,
    *,
    purge_sessions: bool,
    repos: RepoService,
    sessions: SessionManager,
    bus: EventBus,
) -> None:
    """Without `purge_sessions`, a repo that still has sessions (archived too) is refused.

    Purging tolerates a missing repo folder: git cleanup is skipped, rows are deleted.
    """
    repo = repos.get(name)
    owned = [
        *await sessions.list_sessions(repo.name, archived=False),
        *await sessions.list_sessions(repo.name, archived=True),
    ]
    if owned and not purge_sessions:
        msg = (
            f"repo {repo.name!r} still has {len(owned)} session(s); "
            "delete them first or set purge_sessions=true"
        )
        raise RepoInUseError(msg)
    for session in owned:
        await sessions.purge(session.id)
    repos.unregister(repo.name)
    await bus.publish(types.REPO_REMOVED, {"name": repo.name})
