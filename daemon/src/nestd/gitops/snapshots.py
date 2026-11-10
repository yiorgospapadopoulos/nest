"""File checkpoints as git snapshots, on every engine (B145, D174).

Before each user message Nest records the chat's work tree as it is (tracked files and
untracked ones git does not ignore) as a commit under `refs/nest/checkpoints/`, so undo
restores what any tool or shell command changed. A snapshot is written through its own
index file: the user's index, branches and stash are never touched, and no hook runs.

Restoring writes back the files that differ from the snapshot and deletes the ones made
since; ignored files are left as they are, as are the commits and the index. A file made
since that today's ignore rules or the snapshot's ignore is kept too: a turn that changed
`.gitignore` would otherwise cost the user `.env` or a local database (B159 R01). The
snapshot's rules are its `.gitignore` files and the rule files it kept in a parent commit
(`.git/info/exclude`, the one `core.excludesFile` named and the ignored `.gitignore` files),
read in a scratch repository: the checkout and `.git/info/exclude` are never written for it.
Only rule files of the repository's own, or the user's global one, are kept, and only when
they can be read: a snapshot never fails over them (B159 recheck 3).

The folder must be the top of its work tree: a plain folder inside an enclosing repository
(General inside a home folder kept in git) gets no snapshot, and no restore reaches past it.
A restore can be limited to the paths the chat's own turns changed (`only`), so what other
chats or the user changed between its turns stays (B159 R10).
"""

import asyncio
import logging
import os
import shutil
import stat
import tempfile
from collections.abc import AsyncGenerator, Collection, Mapping, Sequence
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
_EXCLUDE = "info/exclude"
# Names in a snapshot's parent commit: `.git/info/exclude`, and what `core.excludesFile`
# named when the snapshot was made.
_KEPT_EXCLUDE = "exclude"
_KEPT_EXCLUDES_FILE = "excludes-file"
# The `.gitignore` files on disk that were ignored themselves, under their own paths.
_KEPT_IGNORE_FILES = "gitignore"
# Where `core.excludesFile` is the user's own setting, not the repository's.
_USER_SCOPES = frozenset({"global", "system"})
_RULE_FILE_LIMIT = 1024 * 1024
# `check-ignore` refuses `--literal-pathspecs`; its paths start with `./` instead, so none
# is read as pathspec magic.
_CHECK_IGNORE_HARDENED = tuple(option for option in HARDENED if option != "--literal-pathspecs")

logger = logging.getLogger(__name__)


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


class NotTheTopError(GitError):
    """The folder lies inside a work tree whose top is another folder."""


async def snapshot(folder: Path, name: str) -> str:
    """Record the work tree at `folder` as the ref `refs/nest/checkpoints/<name>` and
    return the commit; GitError when it is no git work tree's top or git fails.
    """
    git = await _Git.top_at(folder)
    commit = await git.commit_of_work_tree([await git.commit_of_excludes()])
    await git.run(["update-ref", f"{REF_ROOT}/{name}", commit])
    return commit


async def state(folder: Path) -> str:
    """The work tree at `folder` as a commit on no ref, to measure a turn's work from."""
    git = await _Git.top_at(folder)
    return await git.commit_of_work_tree()


async def changed_since(folder: Path, commit: str) -> list[str]:
    """The paths that differ between `commit` and the work tree at `folder` now."""
    git = await _Git.top_at(folder)
    found = await git.changes_since(commit, await git.commit_of_work_tree())
    return [change.path for change in found.changes]


async def changes(folder: Path, commit: str, only: Collection[str] | None = None) -> Changes:
    """What restoring `commit` would change in the work tree at `folder`, of the paths
    `only` names when given.
    """
    git = await _Git.top_at(folder)
    return await git.restorable(commit, only)


async def restore(folder: Path, commit: str, only: Collection[str] | None = None) -> Changes:
    """Put the work tree at `folder` back as it was in `commit`, only the paths `only`
    names when given, and say what changed.
    """
    git = await _Git.top_at(folder)
    found = await git.restorable(commit, only)
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

    @classmethod
    async def top_at(cls, folder: Path) -> "_Git":
        """`at`, refused unless `folder` is the work tree's top (B159 R10)."""
        git = await cls.at(folder)
        if not await asyncio.to_thread(_same_folder, git.top, folder):
            args = ["rev-parse", "--show-toplevel"]
            raise NotTheTopError(args, None, f"{folder} is inside the work tree of {git.top}")
        return git

    async def run(
        self,
        args: Sequence[str],
        index: Path | None = None,
        stdin: str | bytes | None = None,
        hardened: Sequence[str] = HARDENED,
        cwd: Path | None = None,
    ) -> str:
        env = dict(_IDENTITY)
        if index is not None:
            env["GIT_INDEX_FILE"] = str(index)
        argv = ["git", *hardened, *self._overrides, *args]
        where = self.top if cwd is None else cwd
        if stdin is not None:
            return await _with_stdin(args, argv, where, env, stdin)
        try:
            return await run_command(argv, where, TIMEOUT_SECONDS, env=env)
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

    async def restorable(self, commit: str, only: Collection[str] | None = None) -> Changes:
        """What restoring `commit` changes: the differences, of the paths `only` names when
        given, less the files made since that today's or the snapshot's ignore rules
        ignore, which are kept.
        """
        found = await self.changes_since(commit, await self.commit_of_work_tree())
        listed = [c for c in found.changes if only is None or c.path in only]
        made = [c.path for c in listed if c.status == "A"]
        kept = await self.ignored(made)
        kept |= await self.ignored_then(commit, [path for path in made if path not in kept])
        return Changes(found.top, [c for c in listed if c.path not in kept])

    async def ignored(
        self, paths: Sequence[str], where: Path | None = None, settings: Sequence[str] = ()
    ) -> set[str]:
        """Which of `paths` the ignore rules of the work tree at `where` (this one by default)
        ignore, tracked or not."""
        if not paths:
            return set()
        try:
            listing = await self.run(
                ["check-ignore", "--no-index", "-z", "--stdin"],
                stdin="".join(f"./{path}\0" for path in paths),
                hardened=(*_CHECK_IGNORE_HARDENED, *settings),
                cwd=where,
            )
        except GitError as error:
            if error.returncode == 1:  # none is ignored
                return set()
            raise
        return {path.removeprefix("./") for path in listing.split("\0") if path}

    async def commit_of_work_tree(self, parents: Sequence[str] = ()) -> str:
        async with self.index() as index:
            await self.run(["add", "-A", "--", "."], index)
            tree = (await self.run(["write-tree"], index)).strip()
        after = [option for parent in parents for option in ("-p", parent)]
        return (await self.run(["commit-tree", tree, *after, "-m", _MESSAGE])).strip()

    async def exclude_file(self) -> Path:
        path = await self.run(["rev-parse", "--path-format=absolute", "--git-path", _EXCLUDE])
        return Path(path.strip())

    async def excludes_file(self) -> tuple[Path, bool]:
        """The ignore file `core.excludesFile` names, else git's default one, and whether it
        is the user's own: set in their global or system config, or the default."""
        try:
            found = await self.run(
                ["config", "--show-scope", "--path", "--get", "core.excludesFile"]
            )
        except GitError as error:
            if error.returncode != 1:  # 1: not set
                raise
            found = ""
        scope, _, named = found.rstrip("\n").partition("\t")
        if named:
            return self.top / named, scope in _USER_SCOPES
        config = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        return Path(config) / "git" / "ignore", True

    async def commit_of_excludes(self) -> str:
        """A commit whose tree holds `.git/info/exclude`, the `core.excludesFile` file and
        the ignored `.gitignore` files, those that can be kept (`_readable_rules`)."""
        folders = await self.run(
            ["rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir"]
        )
        own = [self.top, *(Path(line) for line in folders.splitlines() if line)]
        excludes, users_own = await self.excludes_file()
        listing = await self.run(
            ["ls-files", "-z", "-o", "-i", "--exclude-standard", "--directory"]
        )
        found: list[tuple[str, Path, Sequence[Path]]] = [
            (_KEPT_EXCLUDE, await self.exclude_file(), own),
            (_KEPT_EXCLUDES_FILE, excludes, () if users_own else own),
            *(
                (f"{_KEPT_IGNORE_FILES}/{path}", self.top / path, own)
                for path in listing.split("\0")
                if _is_ignore_file(path)
            ),
        ]
        entries = ""
        for name, path, inside in found:
            content = await asyncio.to_thread(_readable_rules, path, inside)
            if content is not None:
                blob = await self.run(
                    ["hash-object", "-w", "--stdin", "--no-filters"], stdin=content
                )
                entries += f"100644 {blob.strip()}\t{name}\0"
        handle, name = tempfile.mkstemp(prefix="nest-index-")
        os.close(handle)
        index = Path(name)
        try:
            await asyncio.to_thread(index.unlink)
            await self.run(["update-index", "-z", "--index-info"], index, entries)
            tree = (await self.run(["write-tree"], index)).strip()
        finally:
            await asyncio.to_thread(index.unlink, missing_ok=True)
        return (await self.run(["commit-tree", tree, "-m", _MESSAGE])).strip()

    async def ignored_then(self, commit: str, paths: Sequence[str]) -> set[str]:
        """Which of `paths` the ignore rules of the snapshot `commit` ignore: its `.gitignore`
        files and the exclude files it kept, read in a scratch repository. A snapshot from
        before they were kept has its `.gitignore` files only.
        """
        if not paths:
            return set()
        scratch = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="nest-rules-"))
        try:
            tree = scratch / "tree"
            await self.run(["init", "-q", "--template=", "--", str(tree)])
            listing = await self.run(["ls-tree", "-r", "-z", "--name-only", commit])
            rules = [path for path in listing.split("\0") if _is_ignore_file(path)]
            if rules:
                index = scratch / "index"
                await self.run(["read-tree", commit], index)
                prefix = f"--prefix={tree}/"
                await self.run(["checkout-index", prefix, "-z", "--stdin"], index, "\0".join(rules))
            parent, names = await self._kept_names(commit)
            if _KEPT_IGNORE_FILES in names:
                index = scratch / "ignored-index"
                await self.run(["read-tree", f"{parent}:{_KEPT_IGNORE_FILES}"], index)
                await self.run(["checkout-index", f"--prefix={tree}/", "-f", "-a"], index)
            kept = await self._kept_excludes(parent, names)
            excludes = scratch / _KEPT_EXCLUDES_FILE
            await asyncio.to_thread(_write_kept, tree, excludes, kept)
            setting = excludes if _KEPT_EXCLUDES_FILE in kept else os.devnull
            return await self.ignored(paths, tree, ("-c", f"core.excludesFile={setting}"))
        finally:
            await asyncio.to_thread(shutil.rmtree, scratch, ignore_errors=True)

    async def _kept_names(self, commit: str) -> tuple[str, list[str]]:
        """The parent the snapshot `commit` kept its rule files in, and their top names."""
        parents = (await self.run(["rev-list", "--parents", "-n", "1", commit])).split()[1:]
        if not parents:
            return "", []
        names = (await self.run(["ls-tree", "-z", "--name-only", parents[0]])).split("\0")
        return parents[0], names

    async def _kept_excludes(self, parent: str, names: Sequence[str]) -> dict[str, str]:
        """The exclude files a snapshot kept in `parent`, by name."""
        return {
            name: await self.run(["cat-file", "blob", f"{parent}:{name}"])
            for name in (_KEPT_EXCLUDE, _KEPT_EXCLUDES_FILE)
            if name in names
        }

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


def _is_ignore_file(path: str) -> bool:
    return path.rpartition("/")[2] == ".gitignore"


def _readable_rules(path: Path, inside: Sequence[Path]) -> bytes | None:
    """The content of the rule file at `path` if a snapshot may keep it, else None: a
    regular file of at most `_RULE_FILE_LIMIT` bytes that can be read and, when `inside`
    names folders, is no symlink and lies in one of them. Otherwise a snapshot could store
    a key that `core.excludesFile` or a symlink points at (B159 recheck 3 problem 4).
    """
    if inside:
        try:
            real = path.resolve()
            within = any(real.is_relative_to(folder.resolve()) for folder in inside)
        except (RuntimeError, OSError) as error:
            # A symlink loop raises RuntimeError (B159 recheck 4 problem 1).
            logger.warning("Not keeping %s with the snapshot: %s", path, error)
            return None
        if not within:
            logger.warning("Not keeping %s with the snapshot: outside the repository", path)
            return None
    flags = os.O_RDONLY | os.O_NONBLOCK | (os.O_NOFOLLOW if inside else 0)
    try:
        handle = os.open(path, flags)
    except FileNotFoundError:
        return None
    except OSError as error:
        logger.warning("Not keeping %s with the snapshot: %s", path, error.strerror)
        return None
    with os.fdopen(handle, "rb") as file:
        try:
            info = os.fstat(file.fileno())
            if not stat.S_ISREG(info.st_mode):
                return None
            content = file.read(_RULE_FILE_LIMIT + 1)
        except OSError as error:
            logger.warning("Not keeping %s with the snapshot: %s", path, error.strerror)
            return None
    if len(content) > _RULE_FILE_LIMIT:
        logger.warning("Not keeping %s with the snapshot: over %d bytes", path, _RULE_FILE_LIMIT)
        return None
    return content


def _write_kept(tree: Path, excludes: Path, kept: Mapping[str, str]) -> None:
    """The kept exclude files into the scratch repository at `tree`."""
    if _KEPT_EXCLUDE in kept:
        info = tree / ".git" / "info"
        info.mkdir(parents=True, exist_ok=True)
        (info / "exclude").write_text(kept[_KEPT_EXCLUDE], encoding="utf-8")
    if _KEPT_EXCLUDES_FILE in kept:
        excludes.write_text(kept[_KEPT_EXCLUDES_FILE], encoding="utf-8")


def _same_folder(top: Path, folder: Path) -> bool:
    try:
        return top.samefile(folder)
    except OSError:
        return False


def _copy_index(own: Path, scratch: Path) -> None:
    """The copy keeps the original's modification time: git rechecks a file whose saved stat
    is not older than the index, which catches a same-size edit in the same second.
    """
    try:
        shutil.copy2(own, scratch)
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
    args: Sequence[str],
    argv: Sequence[str],
    cwd: Path,
    env: Mapping[str, str],
    stdin: str | bytes,
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
            data = stdin if isinstance(stdin, bytes) else stdin.encode()
            stdout, stderr = await process.communicate(data)
    except TimeoutError:
        process.kill()
        await process.wait()
        raise GitError(args, None, f"timed out after {TIMEOUT_SECONDS:g} seconds") from None
    if process.returncode:
        raise GitError(args, process.returncode, stderr.decode(errors="replace"))
    return stdout.decode(errors="replace")
