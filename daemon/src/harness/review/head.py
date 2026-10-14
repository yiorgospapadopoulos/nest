"""Where an approved push goes, and the commits on HEAD the review diff does not show.

The review diff compares the base with the working tree, whatever HEAD points to, and an
approved commit goes on top of HEAD as it is. So the review also names HEAD's commit and
branch (SEC-06), and lists the commits on HEAD that neither the base nor the work harness
published holds (SEC-02): commits made behind the review's back, by the agent, a process
it left running or the user, which a push would publish too. Harness's own commits, and
the agent's commits the user chose to publish, are in the published work.

Grafts and a shallow boundary, which the agent can write, make git skip commits; the list
refuses to leave any out that way (SEC-13).
"""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from harness.gitops.runner import GitError, run_git
from harness.review.errors import HiddenHistoryError
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
    paths = await run_git(
        [*safe, "rev-parse", "--git-path", "info/grafts", "--git-path", "shallow"], cwd
    )
    grafts, shallow = (cwd / path for path in paths.splitlines())
    if await asyncio.to_thread(_read_lines, grafts):
        raise HiddenHistoryError(
            "The repository has a grafts file (.git/info/grafts), which can hide commits from "
            "this review. Check it and delete it in Terminal, then open the review again."
        )
    known = [sha for sha in (base, published) if sha is not None]
    output = await run_git(
        [*safe, "rev-list", "--no-commit-header", "--format=%H %s", head, "--not", *known, "--"],
        cwd,
    )
    commits: list[ReviewCommit] = []
    for line in filter(None, output.split("\n")):
        sha, _, subject = line.partition(" ")
        commits.append(ReviewCommit(sha=sha, subject=subject))
    # A listed commit at the shallow boundary has parents git does not show.
    if set(await asyncio.to_thread(_read_lines, shallow)) & {c.sha for c in commits}:
        raise HiddenHistoryError(
            "The repository's shallow history (.git/shallow) hides commits this review would "
            "have to list. Check that file in Terminal, or fetch the whole history with git "
            "fetch --unshallow, then open the review again."
        )
    return commits


def _read_lines(file: Path) -> list[str]:
    """The file's non-blank lines; none when it does not exist."""
    if not file.is_file():
        return []
    return [line.strip() for line in file.read_text(errors="replace").splitlines() if line.strip()]


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
