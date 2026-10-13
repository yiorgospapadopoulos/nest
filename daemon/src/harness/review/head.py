"""Where an approved push goes, and the commits on HEAD the review diff does not show.

The review diff compares the base with the working tree, whatever HEAD points to, and an
approved commit goes on top of HEAD as it is. So the review also names HEAD's commit and
branch (SEC-06), and lists the commits on HEAD that neither the base nor the work harness
published holds (SEC-02): commits made behind the review's back, by the agent, a process
it left running or the user, which a push would publish too. Harness's own commits, and
the agent's commits the user chose to publish, are in the published work.
"""

from collections.abc import Sequence
from pathlib import Path

from harness.gitops.runner import GitError, run_git
from harness.review.models import ReviewCommit, ReviewHead


async def read_head(cwd: Path, safe: Sequence[str]) -> ReviewHead:
    commit = await _optional([*safe, "rev-parse", "--verify", "-q", "HEAD"], cwd)
    ref = await _optional([*safe, "symbolic-ref", "-q", "HEAD"], cwd)
    return ReviewHead(
        commit=commit, branch=None if ref is None else ref.removeprefix("refs/heads/")
    )


async def unaccounted_commits(
    cwd: Path, safe: Sequence[str], head: str | None, base: str | None, published: str | None
) -> list[ReviewCommit]:
    """Commits reachable from `head` but from neither `base` nor `published`, newest first."""
    if head is None:
        return []
    known = [sha for sha in (base, published) if sha is not None]
    output = await run_git(
        [*safe, "rev-list", "--no-commit-header", "--format=%H %s", head, "--not", *known, "--"],
        cwd,
    )
    commits: list[ReviewCommit] = []
    for line in filter(None, output.split("\n")):
        sha, _, subject = line.partition(" ")
        commits.append(ReviewCommit(sha=sha, subject=subject))
    return commits


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
