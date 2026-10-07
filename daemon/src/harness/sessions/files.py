"""File suggestions for @ mentions: the files git knows in a folder, fuzzy-matched (D032).

Tracked files plus untracked ones that are not ignored, listed again at most every few
seconds per folder, so typing a mention does not run git on every key.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from harness.clock import Clock
from harness.gitops.runner import GitError, run_git

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 50
LISTING_TTL = timedelta(seconds=10)

type GitRunner = Callable[[Sequence[str], Path], Awaitable[str]]


@dataclass(frozen=True)
class _Listing:
    files: tuple[str, ...]
    expires: datetime


class FileIndex:
    def __init__(
        self, clock: Clock, git: GitRunner = run_git, ttl: timedelta = LISTING_TTL
    ) -> None:
        self._clock = clock
        self._git = git
        self._ttl = ttl
        self._listings: dict[Path, _Listing] = {}

    async def search(self, cwd: Path, query: str, limit: int = MAX_SUGGESTIONS) -> list[str]:
        """Up to `limit` paths relative to `cwd`, best match first; none outside git."""
        files = await self._files(cwd)
        needle = query.strip().lower()
        ranked = sorted((rank, path) for path in files if (rank := _rank(path, needle)) is not None)
        return [path for _, path in ranked[:limit]]

    async def _files(self, cwd: Path) -> tuple[str, ...]:
        now = self._clock.now()
        listing = self._listings.get(cwd)
        if listing is not None and listing.expires > now:
            return listing.files
        try:
            output = await self._git(
                ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd
            )
        except GitError as error:
            logger.warning("listing the files of %s failed: %s", cwd, error)
            return ()
        files = tuple(dict.fromkeys(path for path in output.split("\0") if path))
        self._listings[cwd] = _Listing(files, now + self._ttl)
        return files


def _rank(path: str, needle: str) -> tuple[int, int] | None:
    """Lower is better: the file name starts with the query, contains it, the path contains
    it, or the query's characters appear in order. Shorter paths win ties.
    """
    if not needle:
        return 0, len(path)
    lowered = path.lower()
    name = lowered.rsplit("/", 1)[-1]
    if name.startswith(needle):
        tier = 0
    elif needle in name:
        tier = 1
    elif needle in lowered:
        tier = 2
    elif _in_order(needle, lowered):
        tier = 3
    else:
        return None
    return tier, len(path)


def _in_order(needle: str, text: str) -> bool:
    remaining = iter(text)
    return all(char in remaining for char in needle)
