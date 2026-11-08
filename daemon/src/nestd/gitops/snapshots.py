"""File checkpoints as git snapshots, on every engine (B145, D174).

Before each user message Nest records the chat's work tree as it is (tracked files and
untracked ones git does not ignore) as a commit under `refs/nest/checkpoints/`, so undo
restores what any tool or shell command changed. A snapshot is written through its own
index file: the user's index, branches and stash are never touched, and no hook runs.

Restoring writes back the files that differ from the snapshot and deletes the ones made
since; ignored files are left as they are, as are the commits and the index.
"""

import asyncio
import os
import tempfile
from collections.abc import AsyncGenerator, Mapping, Sequence
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from pathlib import Path

from nestd.gitops.runner import TIMEOUT_SECONDS, CommandError, GitError, run_command
from nestd.gitops.safety import GIT_CONFIG_LIST, HARDENED, filter_overrides, repo_settings

REF_ROOT = "refs/nest/checkpoints"
# Who the snapshot commits are by; they are on no branch.
_IDENTITY = {
    "GIT_AUTHOR_NAME": "Nest",
    "GIT_AUTHOR_EMAIL": "nest@localhost",
    "GIT_COMMITTER_NAME": "Nest",
    "GIT_COMMITTER_EMAIL": "nest@localhost",
}
_MESSAGE = "Nest checkpoint"
_GITLINK = "160000"


@dataclass(frozen=True)
class Change:
    path: str
    # A: made since the snapshot (restoring deletes it), D: deleted since, M: changed.
    status: str
    insertions: int = 0
    deletions: int = 0


@dataclass(frozen=True)
class Changes:
    """What restoring a snapshot changes, with paths from the work tree's top."""

    top: Path
    changes: list[Change] = field(default_factory=list[Change])

    @property
    def insertions(self) -> int:
        return sum(change.insertions for change in self.changes)

    @property
    def deletions(self) -> int:
        return sum(change.deletions for change in self.changes)


async def snapshot(folder: Path, name: str) -> str:
    """Record the work tree around `folder` as the ref `refs/nest/checkpoints/<name>` and
    return the commit; GitError when it is no git work tree or git fails.
    """
    git = await _Git.at(folder)
    commit = await git.commit_of_work_tree()
    await git.run(["update-ref", f"{REF_ROOT}/{name}", commit])
    return commit


async def changes(folder: Path, commit: str) -> Changes:
    """What restoring `commit` would change in the work tree around `folder`."""
    git = await _Git.at(folder)
    return await git.changes_since(commit, await git.commit_of_work_tree())


async def restore(folder: Path, commit: str) -> Changes:
    """Put the work tree around `folder` back as it was in `commit`, and say what changed."""
    git = await _Git.at(folder)
    found = await git.changes_since(commit, await git.commit_of_work_tree())
    written = [c.path for c in found.changes if c.status != "A"]
    if written:
        async with git.index() as index:
            await git.run(["read-tree", commit], index)
            # Paths go on stdin, so a long list fits and no name is read as an option.
            await git.run(["checkout-index", "-f", "-z", "--stdin"], index, "\0".join(written))
    made = [found.top / c.path for c in found.changes if c.status == "A"]
    await asyncio.to_thread(_delete, made, found.top)
    return found


async def forget(folder: Path, prefix: str) -> None:
    """Delete the refs under `refs/nest/checkpoints/<prefix>/` (a deleted chat's)."""
    git = await _Git.at(folder)
    listing = await git.run(["for-each-ref", "--format=%(refname)", f"{REF_ROOT}/{prefix}/"])
    refs = [line for line in listing.splitlines() if line]
    if refs:
        commands = "".join(f"delete {ref}\n" for ref in refs)
        await git.run(["update-ref", "--stdin"], stdin=commands)


async def copy(folder: Path, commit: str, name: str) -> None:
    """Keep `commit` also as the ref `refs/nest/checkpoints/<name>` (a forked chat's)."""
    git = await _Git.at(folder)
    await git.run(["update-ref", f"{REF_ROOT}/{name}", commit])


class _Git:
    def __init__(self, top: Path, overrides: Sequence[str]) -> None:
        self.top = top
        self._overrides = tuple(overrides)

    @classmethod
    async def at(cls, folder: Path) -> "_Git":
        bare = cls(folder, ())
        top = Path((await bare.run(["rev-parse", "--show-toplevel"])).strip())
        settings = repo_settings(await bare.run(list(GIT_CONFIG_LIST[1:])))
        try:
            # Clean and smudge filters other than git-lfs could run a program (D050).
            overrides = filter_overrides(settings, only_unsafe=True)
        except ValueError as error:
            raise GitError(GIT_CONFIG_LIST[1:], None, str(error)) from None
        return cls(top, overrides)

    async def run(
        self, args: Sequence[str], index: Path | None = None, stdin: str | None = None
    ) -> str:
        env = dict(_IDENTITY)
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        argv = ["git", *HARDENED, *self._overrides, *args]
        if stdin is not None:
            return await _with_stdin(args, argv, self.top, env, stdin)
        try:
            return await run_command(argv, self.top, TIMEOUT_SECONDS, env=env)
        except CommandError as error:
            raise GitError(args, error.returncode, error.stderr) from None

    @asynccontextmanager
    async def index(self) -> AsyncGenerator[Path]:
        """A scratch index, starting as a copy of the work tree's own so unchanged files
        need no hashing; removed afterwards.
        """
        path = await self.run(["rev-parse", "--path-format=absolute", "--git-path", "index"])
        own = Path(path.strip())
        handle, name = tempfile.mkstemp(prefix="nest-index-")
        os.close(handle)
        scratch = Path(name)
        try:
            await asyncio.to_thread(_copy_index, own, scratch)
            yield scratch
        finally:
            await asyncio.to_thread(scratch.unlink, missing_ok=True)

    async def commit_of_work_tree(self) -> str:
        async with self.index() as index:
            await self.run(["add", "-A", "--", "."], index)
            tree = (await self.run(["write-tree"], index)).strip()
        return (await self.run(["commit-tree", tree, "-m", _MESSAGE])).strip()

    async def changes_since(self, before: str, now: str) -> Changes:
        diff = ["diff-tree", "-r", "-z", "--no-renames", "--no-ext-diff", "--no-textconv"]
        statuses = _statuses(await self.run([*diff, "--raw", before, now]))
        counts = _counts(await self.run([*diff, "--numstat", before, now]))
        found = [
            Change(path, status, *counts.get(path, (0, 0)))
            for path, status in statuses.items()
            if status != "G"
        ]
        return Changes(self.top, found)


def _statuses(raw: str) -> dict[str, str]:
    """`diff-tree --raw -z`: `:<mode> <mode> <sha> <sha> <status>\\0<path>\\0` per file;
    submodules are marked `G` so they are left out.
    """
    parts = raw.split("\0")
    found: dict[str, str] = {}
    index = 0
    while index + 1 < len(parts):
        header, path = parts[index], parts[index + 1]
        index += 2
        if not header.startswith(":"):
            continue
        fields = header[1:].split(" ")
        gitlink = _GITLINK in (fields[0], fields[1])
        found[path] = "G" if gitlink else fields[4][:1]
    return found


def _counts(numstat: str) -> dict[str, tuple[int, int]]:
    """`--numstat -z`: `<added>\\t<deleted>\\t<path>\\0`; a binary file counts `-`."""
    found: dict[str, tuple[int, int]] = {}
    for entry in numstat.split("\0"):
        added, _, rest = entry.partition("\t")
        deleted, _, path = rest.partition("\t")
        if path:
            found[path] = (_number(added), _number(deleted))
    return found


def _number(value: str) -> int:
    return int(value) if value.isdigit() else 0


def _copy_index(own: Path, scratch: Path) -> None:
    try:
        scratch.write_bytes(own.read_bytes())
    except FileNotFoundError:
        # A repository with nothing staged yet has no index.
        scratch.unlink(missing_ok=True)


def _delete(paths: Sequence[Path], top: Path) -> None:
    """Delete the files and the folders they leave empty, up to the work tree's top."""
    for path in paths:
        with suppress(FileNotFoundError):
            path.unlink()
        parent = path.parent
        while parent != top and parent.is_relative_to(top):
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent


async def _with_stdin(
    args: Sequence[str], argv: Sequence[str], cwd: Path, env: Mapping[str, str], stdin: str
) -> str:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, **env},
    )
    try:
        async with asyncio.timeout(TIMEOUT_SECONDS):
            stdout, stderr = await process.communicate(stdin.encode())
    except TimeoutError:
        process.kill()
        await process.wait()
        raise GitError(args, None, f"timed out after {TIMEOUT_SECONDS:g} seconds") from None
    if process.returncode:
        raise GitError(args, process.returncode, stderr.decode(errors="replace"))
    return stdout.decode(errors="replace")
