"""Where an approved commit goes: HEAD's commit, which the review compares the working tree
with, and the branch an approved push goes to (SEC-06).
"""

from collections.abc import Sequence
from pathlib import Path

from nestd.gitops.runner import GitError, run_git
from nestd.review.models import ReviewHead


async def read_head(cwd: Path, safe: Sequence[str]) -> ReviewHead:
    commit = await _optional([*safe, "rev-parse", "--verify", "-q", "HEAD"], cwd)
    ref = await _optional([*safe, "symbolic-ref", "-q", "HEAD"], cwd)
    return ReviewHead(
        commit=commit, branch=None if ref is None else ref.removeprefix("refs/heads/")
    )


async def _optional(args: list[str], cwd: Path) -> str | None:
    """The command's output, or None when it exits with 1: no commits yet, or a detached
    HEAD. Any other failure is raised.
    """
    try:
        return (await run_git(args, cwd)).strip()
    except GitError as error:
        if error.returncode == 1:
            return None
        raise
