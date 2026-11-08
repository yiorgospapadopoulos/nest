"""Merged worktrees go by themselves in projects that turn `clean_merged` on (B141).

A worktree goes when Nest made it, no open chat works in it, it is on a branch other than
the default one, it has commits since it was made, and it holds nothing removing it would
lose (`at_risk`): no changes, no untracked files and no commit the default branch lacks.
So a merged worktree goes and nothing is lost; one nobody committed in stays. Its branch
stays too.

Each project is checked once at start and whenever its branches change (B96), as after a
merge, one project at a time.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from pathlib import Path

from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.events.bus import EventBus, SubscriptionOverflowError
from nestd.gitops.hardened import run_hardened_git
from nestd.gitops.runner import GitError
from nestd.repos.branch_map import Checkout, checkouts
from nestd.repos.service import RepoNotFoundError, RepoService
from nestd.sessions.rules import among
from nestd.sessions.store import SessionStore
from nestd.worktrees.manager import Worktree, WorktreeManager

logger = logging.getLogger(__name__)

# Removes the worktree unless an open chat works in it or Nest did not make it.
type RemoveUnused = Callable[[RepoConfig, Worktree], Awaitable[bool]]


class MergedWorktrees:
    def __init__(
        self,
        *,
        repos: RepoService,
        store: SessionStore,
        worktrees: WorktreeManager,
        remove: RemoveUnused,
        bus: EventBus,
    ) -> None:
        self._repos = repos
        self._store = store
        self._worktrees = worktrees
        self._remove = remove
        self._bus = bus
        self._due: set[str] = set()
        self._wake = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        self._due.update(repo.name for repo in self._repos.list_repos())
        self._wake.set()
        self._tasks = [asyncio.create_task(self._listen()), asyncio.create_task(self._work())]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []

    async def sweep(self, repo: RepoConfig) -> list[Path]:
        """Remove the project's merged worktrees, if it cleans them; returns those removed."""
        if not repo.git or repo.default_branch is None:
            return []
        if not self._worktrees.options(repo).clean_merged:
            return []
        base = await _tip(repo.path, f"refs/heads/{repo.default_branch}")
        if base is None:
            return []
        _, *linked = await checkouts(repo.path)
        users = await self._store.worktree_users(())
        starts = await asyncio.to_thread(_resolved, await self._store.worktree_bases(repo.name))
        removed: list[Path] = []
        for checkout in linked:
            # Where it started: the commit it was made at, else the default branch's tip.
            start = starts.get(await asyncio.to_thread(checkout.path.resolve), base)
            if await self._merged(repo, checkout, start, users):
                worktree = Worktree(checkout.path, checkout.branch or "", "")
                if await self._remove(repo, worktree):
                    logger.info("removed the merged worktree %s of %s", checkout.path, repo.name)
                    removed.append(checkout.path)
        return removed

    async def _merged(
        self, repo: RepoConfig, checkout: Checkout, start: str, users: list[Path]
    ) -> bool:
        path = checkout.path
        if checkout.branch is None or checkout.branch == repo.default_branch:
            return False
        if not await asyncio.to_thread(self._worktrees.owns, repo, path):
            return False
        if await asyncio.to_thread(among, path, users):
            return False
        if await _tip(path, "HEAD") in (None, start):
            return False
        try:
            risk = await self._worktrees.at_risk(repo, Worktree(path, checkout.branch, ""))
        except GitError as error:
            logger.debug("checking the worktree %s failed (%s)", path, error)
            return False
        return risk.empty

    async def _listen(self) -> None:
        while True:
            try:
                async with aclosing(self._bus.subscribe()) as events:
                    async for event in events:
                        if event.type == types.REPO_BRANCHES_CHANGED:
                            self._due.add(str(event.payload["name"]))
                            self._wake.set()
            except SubscriptionOverflowError:
                self._due.update(repo.name for repo in self._repos.list_repos())
                self._wake.set()

    async def _work(self) -> None:
        while True:
            await self._wake.wait()
            self._wake.clear()
            while self._due:
                name = self._due.pop()
                try:
                    await self.sweep(self._repos.get(name))
                except (RepoNotFoundError, GitError) as error:
                    logger.debug("cleaning the merged worktrees of %s failed (%s)", name, error)
                except Exception:
                    logger.exception("cleaning the merged worktrees of %s failed", name)


def _resolved(bases: dict[Path, str]) -> dict[Path, str]:
    return {path.resolve(): commit for path, commit in bases.items()}


async def _tip(path: Path, ref: str) -> str | None:
    try:
        output = await run_hardened_git(["rev-parse", "--verify", "--quiet", ref], path)
    except GitError:
        return None
    return output.strip() or None
