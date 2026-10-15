"""File suggestions for @ mentions: the files in a folder, fuzzy-matched (D032).

In a git repository, tracked files plus untracked ones that are not ignored; in a plain
folder or a pixie's workdir, a walk that skips hidden, dependency and build folders (B59).
Listed again at most every few seconds per folder, so typing a mention does not list the
folder on every key.
"""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from nestd.clock import Clock
from nestd.gitops.hardened import run_hardened_git
from nestd.gitops.runner import GitError

logger = logging.getLogger(__name__)

MAX_SUGGESTIONS = 50
LISTING_TTL = timedelta(seconds=10)
# A walk stops after this many files, so a huge folder does not stall the composer.
MAX_WALKED_FILES = 20_000
# Folders a walk skips besides hidden ones: dependencies and build output.
SKIPPED_FOLDERS = frozenset(
    {"node_modules", "venv", "__pycache__", "build", "dist", "target", "DerivedData", "Pods"}
)

type GitRunner = Callable[[Sequence[str], Path], Awaitable[str]]


@dataclass(frozen=True)
class _Listing:
    files: tuple[str, ...]
    expires: datetime


class FileIndex:
    def __init__(
        self,
        clock: Clock,
        git: GitRunner = run_hardened_git,
        ttl: timedelta = LISTING_TTL,
        max_walked: int = MAX_WALKED_FILES,
    ) -> None:
        self._clock = clock
        self._git = git
        self._ttl = ttl
        self._max_walked = max_walked
        self._listings: dict[tuple[Path, bool], _Listing] = {}

    async def search(
        self, cwd: Path, query: str, limit: int = MAX_SUGGESTIONS, *, git: bool = True
    ) -> list[str]:
        """Up to `limit` paths relative to `cwd`, best match first. `git` lists what git
        knows (none when that fails); otherwise the folder is walked.
        """
        files = await self._files(cwd, git)
        needle = query.strip().lower()
        ranked = sorted((rank, path) for path in files if (rank := _rank(path, needle)) is not None)
        return [path for _, path in ranked[:limit]]

    async def _files(self, cwd: Path, git: bool) -> tuple[str, ...]:
        now = self._clock.now()
        listing = self._listings.get((cwd, git))
        if listing is not None and listing.expires > now:
            return listing.files
        if git:
            files = await self._git_files(cwd)
        else:
            files = await asyncio.to_thread(_walk, cwd, self._max_walked)
        self._listings[(cwd, git)] = _Listing(files, now + self._ttl)
        return files

    async def _git_files(self, cwd: Path) -> tuple[str, ...]:
        try:
            output = await self._git(
                ["ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd
            )
        except GitError as error:
            logger.warning("listing the files of %s failed: %s", cwd, error)
            return ()
        return tuple(dict.fromkeys(path for path in output.split("\0") if path))


def _walk(root: Path, limit: int) -> tuple[str, ...]:
    """Files under `root`, relative to it, without following links into other folders."""
    found: list[str] = []
    for folder, dirs, names in os.walk(root):
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in SKIPPED_FOLDERS)
        base = Path(folder).relative_to(root)
        for name in sorted(names):
            found.append((base / name).as_posix())
            if len(found) >= limit:
                return tuple(found)
    return tuple(found)


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
