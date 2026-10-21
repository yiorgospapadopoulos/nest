"""The repository paths changed since the merge base with a base ref, from git."""

import subprocess
from pathlib import Path

from nestd.gates.errors import GatesError


def _git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise GatesError(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def repository_root(cwd: Path) -> Path:
    return Path(_git(cwd, "rev-parse", "--show-toplevel").strip())


def merge_base(root: Path, base: str) -> str:
    return _git(root, "merge-base", base, "HEAD").strip()


def changed_paths(root: Path, since: str) -> list[str]:
    """Committed, staged, unstaged and untracked (not ignored) paths changed since `since`.

    Renames are listed as a deletion and an addition, so a move between parts runs both.
    """
    tracked = _git(root, "diff", "--name-only", "--no-renames", "-z", since)
    untracked = _git(root, "ls-files", "--others", "--exclude-standard", "-z")
    return sorted({path for path in (tracked + untracked).split("\0") if path})
