"""A session's work as a diff: its working tree, untracked files included, against its base.

The diff runs with the user's credentials in a tree the agent could change, so git runs
with no hooks, fsmonitor, textconv or external diff, and with the repository's own filter
drivers switched off (D050).
"""

from pathlib import Path

from harness.gitops.runner import GitError, run_git
from harness.gitops.safety import GIT_CONFIG_LIST, HARDENED, filter_overrides, repo_settings
from harness.review.diff_parser import PatchFile, by_path, parse_name_status, parse_patch
from harness.review.models import DiffStats, FileDiff, FileStatus, SessionDiff
from harness.review.untracked import untracked_diff

MAX_LINES_PER_FILE = 2000
# Git's empty tree, the base of a repository without commits.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


async def session_diff(cwd: Path, base: str | None) -> SessionDiff:
    ref = base or EMPTY_TREE
    safe = await _safe_options(cwd)
    # The same rename detection for both, so git lists the files in the same order.
    statuses = await run_git(
        [*safe, "diff", "--no-ext-diff", "--no-textconv", "-z", "--name-status", "-M", ref, "--"],
        cwd,
    )
    patch = await run_git(
        [*safe, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-M", ref, "--"], cwd
    )
    untracked = await run_git([*safe, "ls-files", "--others", "--exclude-standard", "-z"], cwd)
    # By path, not position: a typechange is one status but two patch sections, and the
    # agent may still change the tree between the two commands.
    parts = by_path(parse_patch(patch, MAX_LINES_PER_FILE))
    files = [
        _file(path, old_path, status, parts.get(path) or PatchFile(path))
        for status, old_path, path in parse_name_status(statuses)
    ]
    for path in filter(None, untracked.split("\0")):
        files.append(await untracked_diff(cwd, path, MAX_LINES_PER_FILE))
    files.sort(key=lambda f: f.path)
    return SessionDiff(
        base=base,
        files=files,
        stats=DiffStats(
            files=len(files),
            additions=sum(f.additions for f in files),
            deletions=sum(f.deletions for f in files),
        ),
    )


def _file(path: str, old_path: str | None, status: FileStatus, part: PatchFile) -> FileDiff:
    return FileDiff(
        path=path,
        old_path=old_path,
        status=status,
        additions=part.additions,
        deletions=part.deletions,
        binary=part.binary,
        truncated=part.truncated,
        hunks=part.hunks,
    )


async def _safe_options(cwd: Path) -> list[str]:
    args = GIT_CONFIG_LIST[1:]
    settings = repo_settings(await run_git(args, cwd))
    try:
        return [*HARDENED, *filter_overrides(settings)]
    except ValueError as error:
        raise GitError(args, None, str(error)) from None
