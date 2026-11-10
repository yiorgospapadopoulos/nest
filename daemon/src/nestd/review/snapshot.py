"""The reviewed work as git objects, so approving commits exactly what the review showed
(B159 P-1).

The review stages the tracked changes into an index of its own (`GIT_INDEX_FILE`), never
the checkout's, and shows the diff of that index: what it shows comes from blobs, which
cannot change afterwards. Approving reads the work the same way, checks its fingerprint,
and builds the commit's tree from those very entries; nothing reads the working files
again between the check and the commit.
"""

import tempfile
from collections.abc import AsyncGenerator, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from nestd.gitops.runner import run_git
from nestd.gitops.safety import HARDENED

# The mode of a path the work deletes.
DELETED = "000000"
# Paths per git command, well under the system's limit on a command line.
_BATCH = 500


@dataclass(frozen=True)
class IndexEntry:
    """One path of the work as it is to be committed: its mode and object, or DELETED."""

    mode: str
    oid: str
    path: str


class WorkIndex:
    """An index file of its own, in a folder of its own."""

    def __init__(self, cwd: Path, folder: Path) -> None:
        self.cwd = cwd
        # For files that go into the object database exactly as they were read.
        self.folder = folder
        self._env = {"GIT_INDEX_FILE": str(folder / "index")}

    async def git(self, args: Sequence[str]) -> str:
        return await run_git(args, self.cwd, env=self._env)


@asynccontextmanager
async def work_index(cwd: Path, base: str | None) -> AsyncGenerator[WorkIndex]:
    """An index holding `base`'s tree (none for a repository without commits)."""
    with tempfile.TemporaryDirectory(prefix="nest-index-") as folder:
        index = WorkIndex(cwd, Path(folder))
        await index.git([*HARDENED, "read-tree", *((base,) if base else ("--empty",))])
        yield index


def parse_entries(raw: str) -> list[IndexEntry]:
    """The new side of each path of `git diff --raw -z --no-abbrev --no-renames`."""
    tokens = iter(raw.split("\0"))
    entries: list[IndexEntry] = []
    for meta in tokens:
        if not meta:
            continue
        _, new_mode, _, new_oid, _ = meta.removeprefix(":").split(" ")
        entries.append(IndexEntry(new_mode, new_oid, next(tokens)))
    return entries


def batches[T](items: Sequence[T]) -> list[Sequence[T]]:
    """`items` in slices small enough for one command line each."""
    return [items[start : start + _BATCH] for start in range(0, len(items), _BATCH)]


def index_updates(entries: Sequence[IndexEntry]) -> list[list[str]]:
    """`update-index` arguments that apply `entries` to an index: removals first, then
    the rest, each replacing whatever stands in its way (a file where a folder goes).
    """
    removed = [entry.path for entry in entries if entry.mode == DELETED]
    added = [entry for entry in entries if entry.mode != DELETED]
    updates = [["--force-remove", "--", *paths] for paths in batches(removed)]
    for batch in batches(added):
        info = [arg for e in batch for arg in ("--cacheinfo", e.mode, e.oid, e.path)]
        updates.append(["--add", "--replace", *info])
    return updates


async def write_tree(cwd: Path, base: str | None, entries: Sequence[IndexEntry]) -> str:
    """The tree of `base` with `entries` applied, written without touching the checkout's
    index or files.
    """
    async with work_index(cwd, base) as index:
        for update in index_updates(entries):
            await index.git([*HARDENED, "update-index", *update])
        return (await index.git([*HARDENED, "write-tree"])).strip()
