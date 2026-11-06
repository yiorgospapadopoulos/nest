"""The branch map's reload (B131): fetch every remote of a project, side by side, so one
hung or dead remote never holds up the others. Only that remote's tracking refs change.
"""

import asyncio
import re

from pydantic import BaseModel

from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.hardened import remote_names, run_fetch_git, run_hardened_git
from nestd.gitops.remotes import scrub_credentials
from nestd.gitops.runner import GitError
from nestd.gitops.safety import GIT_CONFIG_LIST, fetch_blockers, repo_settings
from nestd.repos.service import RepoUnreadableError

FETCH_TIME_LIMIT = 120.0
# Anything else, such as `*` or `:`, could change the refspec a fetch is given.
_SAFE_REMOTE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")


class FetchedRemote(BaseModel):
    name: str
    # Why it could not be fetched; null when it was.
    error: str | None


class RefreshReport(BaseModel):
    remotes: list[FetchedRemote]


class RepoFetcher:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        # Two clicks fetch one after the other, not over each other.
        self._locks: dict[str, asyncio.Lock] = {}

    async def refresh(self, repo: RepoConfig) -> RefreshReport:
        """Settings that a fetch would obey and that run a program or send data elsewhere
        stop it for every remote, with the reason; the local map reads as before.
        """
        async with self._locks.setdefault(repo.name, asyncio.Lock()):
            try:
                names = await remote_names(repo.path)
                listing = await run_hardened_git(GIT_CONFIG_LIST[1:], repo.path)
            except GitError as error:
                raise RepoUnreadableError(error) from None
            blockers = fetch_blockers(repo_settings(listing))
            if blockers:
                reason = f"the project's git settings stop a fetch: {', '.join(blockers)}"
                remotes = [FetchedRemote(name=name, error=reason) for name in names]
            else:
                remotes = await asyncio.gather(*(_fetch(repo, name) for name in names))
        await self._bus.publish_ephemeral(types.REPO_BRANCHES_CHANGED, {"name": repo.name})
        return RefreshReport(remotes=list(remotes))


async def _fetch(repo: RepoConfig, remote: str) -> FetchedRemote:
    if not _SAFE_REMOTE.fullmatch(remote) or ".." in remote:
        return FetchedRemote(name=remote, error="Nest cannot fetch a remote with this name")
    try:
        await run_fetch_git(remote, repo.path, FETCH_TIME_LIMIT)
    except GitError as error:
        lines = error.stderr.strip().splitlines() or [str(error)]
        return FetchedRemote(name=remote, error=scrub_credentials(lines[0]))
    return FetchedRemote(name=remote, error=None)
