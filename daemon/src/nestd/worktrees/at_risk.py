"""What removing a worktree would lose (B141): uncommitted changes, untracked files and
commits that are not on the base branch. Ignored files do not count, as they are what a
build or `link` puts there.
"""

from collections.abc import Collection
from dataclasses import dataclass
from pathlib import Path

from nestd.gitops.hardened import run_checkout_git, run_hardened_git

# How many files and commits the warning names; the rest are counted.
SHOWN = 20


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str


@dataclass(frozen=True)
class AtRisk:
    # The branch or commit the commits were compared with; None when there was none.
    base: str | None
    changed: tuple[str, ...] = ()
    untracked: tuple[str, ...] = ()
    commits: tuple[Commit, ...] = ()

    @property
    def files(self) -> tuple[str, ...]:
        return self.changed + self.untracked

    @property
    def empty(self) -> bool:
        return not (self.files or self.commits)

    def covered_by(self, files: Collection[str], commits: Collection[str]) -> bool:
        """Whether all of it was in what the user agreed to lose."""
        return set(self.files) <= set(files) and {c.sha for c in self.commits} <= set(commits)

    def summary(self) -> str:
        """One line, such as "2 uncommitted files, 1 untracked file and 3 commits not on main"."""
        parts = [
            _count(len(self.changed), "uncommitted file"),
            _count(len(self.untracked), "untracked file"),
            _count(len(self.commits), "commit") + f" not on {self.base}" if self.commits else "",
        ]
        shown = [part for part in parts if part]
        return shown[0] if len(shown) == 1 else ", ".join(shown[:-1]) + " and " + shown[-1]

    def details(self) -> str:
        """The files and commits by name, a block of lines for the warning."""
        lines: list[str] = []
        if self.changed:
            lines += ["Uncommitted changes:", *_listed(list(self.changed))]
        if self.untracked:
            lines += ["Untracked files:", *_listed(list(self.untracked))]
        if self.commits:
            named = [f"{c.sha[:7]} {c.subject}" for c in self.commits]
            lines += [f"Commits not on {self.base}:", *_listed(named)]
        return "\n".join(lines)


async def at_risk(path: Path, base: str | None, base_name: str | None = None) -> AtRisk:
    """What the worktree at `path` holds that removing it would lose, its commits compared
    with `base` (a ref or commit, shown as `base_name`; None skips them). Raises GitError
    when git cannot tell.
    """
    # Submodules count with their own changes: those go with the folder too.
    status = await run_checkout_git(
        ["status", "--porcelain=v1", "-z", "--ignore-submodules=none"], path
    )
    changed, untracked = _status(status)
    commits: tuple[Commit, ...] = ()
    if base is not None:
        log = await run_hardened_git(
            ["log", "--format=%H%x00%s", "HEAD", "--not", base, "--"], path
        )
        commits = tuple(Commit(*line.split("\0", 1)) for line in log.splitlines() if line)
    return AtRisk(base_name or base, changed, untracked, commits)


def _status(output: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Changed and untracked paths from `git status --porcelain=v1 -z`."""
    changed: list[str] = []
    untracked: list[str] = []
    entries = iter(output.split("\0"))
    for entry in entries:
        if len(entry) < 4:
            continue
        code, name = entry[:2], entry[3:]
        if code == "??":
            untracked.append(name)
            continue
        changed.append(name)
        if code[0] in "RC":
            next(entries, None)  # the name it had before
    return tuple(changed), tuple(untracked)


def _listed(items: list[str]) -> list[str]:
    shown = [f"  {item}" for item in items[:SHOWN]]
    if len(items) > SHOWN:
        shown.append(f"  and {len(items) - SHOWN} more")
    return shown


def _count(number: int, noun: str) -> str:
    if number == 0:
        return ""
    return f"{number} {noun}" if number == 1 else f"{number} {noun}s"
