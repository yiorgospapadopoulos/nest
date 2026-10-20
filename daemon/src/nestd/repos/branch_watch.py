"""Announce a git project's branch map changing (B96), whoever changed it: a worktree
added or removed by Nest, Claude Code or a terminal, or the project folder switched to
another branch.

Every few seconds each git project's `git worktree list` (which names the project
folder's branch) is compared with the last scan's. The first scan of a project only
records it.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.hardened import run_hardened_git
from nestd.gitops.runner import GitError
from nestd.repos.service import RepoService

logger = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=2)


class BranchWatch:
    def __init__(
        self, *, repos: RepoService, bus: EventBus, interval: timedelta = POLL_INTERVAL
    ) -> None:
        self._repos = repos
        self._bus = bus
        self._interval = interval
        self._signatures: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None

    async def scan(self) -> None:
        """Announce each git project whose signature changed since the last scan. One that
        git cannot read keeps its last signature and does not hold up the others.
        """
        signatures: dict[str, str] = {}
        for repo in self._repos.list_repos():
            if not repo.git:
                continue
            try:
                signatures[repo.name] = await run_hardened_git(
                    ["worktree", "list", "--porcelain", "-z"], repo.path
                )
            except GitError as error:
                logger.debug("reading the worktrees of %s failed (%s)", repo.name, error)
                if repo.name in self._signatures:
                    signatures[repo.name] = self._signatures[repo.name]
                continue
            known = self._signatures.get(repo.name)
            if known is not None and known != signatures[repo.name]:
                await self._bus.publish_ephemeral(types.REPO_BRANCHES_CHANGED, {"name": repo.name})
        self._signatures = signatures

    async def start(self) -> None:
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _poll(self) -> None:
        while True:
            try:
                await self.scan()
            except Exception:
                logger.exception("watching the branches of the projects failed")
            await asyncio.sleep(self._interval.total_seconds())
