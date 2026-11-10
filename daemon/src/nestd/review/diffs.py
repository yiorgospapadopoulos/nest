"""A session's work as a diff: its working tree, untracked files included, against HEAD.

The review covers what is not committed yet (B58): the agent may commit when the user
asks, as in the terminal, and its commits are the chat's business, not the review's.

The diff runs with the user's credentials in a tree the agent could change, so git runs
with no hooks, fsmonitor, textconv, external diff or replace refs, and with the
repository's own filter drivers switched off (D050). It never looks inside a submodule or
nested repository, whose own config could name a filter (SEC-08), yet always shows a new
submodule pointer, whatever the config says (SEC-12). A file is binary only by its content,
never by attributes or settings (SEC-09). The patch's `a/` and `b/` prefixes are pinned,
since the files are matched to their patch sections by path and the repository's config
may change the prefixes (BUG-52).

The fingerprint covers everything approving would publish, so an approval is tied to the
review the user saw. The tracked changes are shown from an index of the review's own, the
untracked files from one read each, and approving commits those same objects (B159 P-1).
"""

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from nestd.gitops.runner import GitError, run_git
from nestd.gitops.safety import GIT_CONFIG_LIST, HARDENED, filter_overrides, repo_settings
from nestd.review.diff_parser import PatchFile, RawEntry, by_path, parse_patch, parse_raw
from nestd.review.head import read_head
from nestd.review.models import DiffStats, FileDiff, ReviewHead, SessionDiff
from nestd.review.snapshot import IndexEntry, WorkIndex, batches, parse_entries, work_index
from nestd.review.untracked import REGULAR, SYMLINK, is_text, untracked_diff

MAX_LINES_PER_FILE = 2000
# Git's empty tree, the base of a repository without commits.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
GITLINK = "160000"
GITMODULES = ".gitmodules"


@dataclass(frozen=True)
class ReviewedWork:
    diff: SessionDiff
    # Every path the work changes, as approving commits it, its objects written.
    entries: list[IndexEntry]


async def session_diff(cwd: Path) -> SessionDiff:
    """The changes in `cwd` that are not committed: staged, unstaged and untracked."""
    return (await _review(cwd, keep=False)).diff


async def reviewed_work(cwd: Path) -> ReviewedWork:
    """The review as `session_diff` makes it, with each change as the object approving
    commits: the tracked ones staged for the review, the untracked ones written from the
    very bytes the review read (B159 P-1).
    """
    return await _review(cwd, keep=True)


async def _review(cwd: Path, *, keep: bool) -> ReviewedWork:
    safe = await _safe_options(cwd)
    # HEAD's commit, read once, so both diffs and the review name the same one.
    head = await read_head(cwd, safe)
    ref = head.commit or EMPTY_TREE
    async with work_index(cwd, head.commit) as index:
        await _stage_tracked(index, safe, ref)
        # The same rename detection for both, so git lists the files in the same order.
        diff = [*safe, "diff", "--cached", "--no-color", "--no-ext-diff", "--no-textconv"]
        diff += ["--ignore-submodules=dirty", "-M"]
        statuses = await index.git([*diff, "-z", "--raw", "--no-abbrev", ref, "--"])
        patch_args = [*diff, "--full-index", "--src-prefix=a/", "--dst-prefix=b/", ref]
        patch = await index.git([*patch_args, "--"])
        untracked = await run_git([*safe, "ls-files", "--others", "--exclude-standard", "-z"], cwd)
        entries = parse_raw(statuses)
        # By path, not position: a typechange is one status but two patch sections.
        parts = by_path(parse_patch(patch, MAX_LINES_PER_FILE))
        text_patch = await _patch_as_text(index, patch_args, entries, parts)
        parts.update(by_path(parse_patch(text_patch, MAX_LINES_PER_FILE)))
        declared = await _declared_submodules(cwd, safe, entries)
        files = [
            _file(entry, parts.get(entry.path) or PatchFile(entry.path), declared)
            for entry in entries
        ]
        committed: list[IndexEntry] = []
        if keep:
            changes = [*safe, "diff", "--cached", "--raw", "-z", "--no-abbrev", "--no-renames"]
            committed = parse_entries(await index.git([*changes, ref, "--"]))
        trusts_mode = keep and await _trusts_executable_bit(cwd, safe)
        digests: list[tuple[str, str]] = []
        for number, path in enumerate(filter(None, untracked.split("\0"))):
            copy = index.folder / f"untracked-{number}" if keep and not path.endswith("/") else None
            found = await untracked_diff(cwd, path, MAX_LINES_PER_FILE, copy)
            files.append(found.diff)
            digests.append((path, found.digest))
            if copy is not None:
                mode = found.mode if trusts_mode or found.mode == SYMLINK else REGULAR
                committed.append(IndexEntry(mode, await _blob(cwd, safe, path, mode, copy), path))
    files.sort(key=lambda f: f.path)
    return ReviewedWork(
        diff=SessionDiff(
            base=head.commit,
            head=head,
            files=files,
            stats=DiffStats(
                files=len(files),
                additions=sum(f.additions for f in files),
                deletions=sum(f.deletions for f in files),
            ),
            fingerprint=_fingerprint(head, files, statuses, patch, text_patch, digests),
        ),
        entries=committed,
    )


async def _stage_tracked(index: WorkIndex, safe: Sequence[str], ref: str) -> None:
    """Stage into the review's own index every tracked path whose file differs from `ref`,
    as `git add` would; the checkout's index only tells which paths these are.
    """
    names = [*safe, "diff", "--name-only", "-z", "--no-renames", "--ignore-submodules=dirty"]
    listing = await run_git([*names, ref, "--"], index.cwd)
    for paths in batches([path for path in listing.split("\0") if path]):
        await index.git([*safe, "update-index", "--add", "--remove", "--", *paths])


async def _trusts_executable_bit(cwd: Path, safe: Sequence[str]) -> bool:
    """Whether git records a new file's executable bit (`core.fileMode`)."""
    setting = [*safe, "config", "--type=bool", "--default=true", "core.fileMode"]
    return (await run_git(setting, cwd)).strip() == "true"


async def _blob(cwd: Path, safe: Sequence[str], path: str, mode: str, copy: Path) -> str:
    """Write `copy`, read from the untracked file at `path`, as `git add` would store it."""
    how = "--no-filters" if mode == SYMLINK else f"--path={path}"
    return (await run_git([*safe, "hash-object", "-w", how, "--", str(copy)], cwd)).strip()


def _file(entry: RawEntry, part: PatchFile, declared: set[str]) -> FileDiff:
    return FileDiff(
        path=entry.path,
        old_path=entry.old_path,
        status=entry.status,
        additions=part.additions,
        deletions=part.deletions,
        binary=part.binary,
        truncated=part.truncated,
        hunks=part.hunks,
        nested_repository=_new_gitlink(entry) and entry.path not in declared,
    )


def _new_gitlink(entry: RawEntry) -> bool:
    return entry.new_mode == GITLINK and entry.old_mode != GITLINK


async def _patch_as_text(
    index: WorkIndex,
    patch_args: Sequence[str],
    entries: list[RawEntry],
    parts: dict[str, PatchFile],
) -> str:
    """The patch, as text, of the files git called binary that git's own content test finds
    text: attributes and settings the agent can write make git call any file binary, while
    `git add` commits it all the same (SEC-09). A deleted file commits no content, so git's
    word stands there.
    """
    paths: list[str] = []
    for entry in entries:
        part = parts.get(entry.path)
        if (
            part is not None
            and part.binary
            and await asyncio.to_thread(is_text, index.cwd / entry.path)
        ):
            paths += [entry.path] if entry.old_path is None else [entry.path, entry.old_path]
    if not paths:
        return ""
    return await index.git([*patch_args, "--text", "--", *paths])


async def _declared_submodules(cwd: Path, safe: Sequence[str], entries: list[RawEntry]) -> set[str]:
    """The paths `.gitmodules` declares as submodules, read only when the work stages a new
    gitlink, and only from a `.gitmodules` that is committed with the work: one that is
    ignored never reaches the pushed branch (SEC-14).
    """
    if not any(_new_gitlink(entry) for entry in entries):
        return set()
    listing = [*safe, "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
    if not await run_git([*listing, "--", GITMODULES], cwd):
        return set()
    try:
        config = await run_git([*safe, "config", "--file", GITMODULES, "--list", "-z"], cwd)
    except GitError:
        return set()  # gone from the tree, or not a config file git can read
    declared: set[str] = set()
    for item in filter(None, config.split("\0")):
        key, _, value = item.partition("\n")
        if key.startswith("submodule.") and key.endswith(".path"):
            declared.add(value)
    return declared


def _fingerprint(
    head: ReviewHead,
    files: list[FileDiff],
    *outputs: str | list[tuple[str, str]],
) -> str:
    """A digest of what the review shows and of git's own output it came from: the patch
    holds each file's full blob ids and modes, and the digests cover untracked files whole.
    """
    digest = sha256()
    parts = [
        head.model_dump_json(),
        json.dumps([file.model_dump() for file in files]),
        *(json.dumps(output) for output in outputs),
    ]
    for part in parts:
        data = part.encode()
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


async def _safe_options(cwd: Path) -> list[str]:
    args = [*HARDENED, *GIT_CONFIG_LIST[1:]]
    settings = repo_settings(await run_git(args, cwd))
    try:
        return [*HARDENED, *filter_overrides(settings)]
    except ValueError as error:
        raise GitError(args, None, str(error)) from None
