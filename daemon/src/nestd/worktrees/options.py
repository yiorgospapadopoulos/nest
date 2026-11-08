"""A project's worktree choices: its own `[worktree]` keys, else `[worktrees]` (B141)."""

from dataclasses import dataclass
from pathlib import Path

from nestd.config.models import RepoConfig, WorktreeDefaults

# Run in a new worktree before the project's setup commands when submodules are on.
SUBMODULES_COMMAND = "git submodule update --init --recursive"


def claude_worktrees_dir(repo_path: Path) -> Path:
    """Where Claude Code keeps a project's worktrees, and Nest by default (D028)."""
    return repo_path / ".claude" / "worktrees"


@dataclass(frozen=True)
class WorktreeOptions:
    # Where the project's new worktrees go.
    folder: Path
    branch_prefix: str
    clean_merged: bool
    submodules: bool


def options_for(repo: RepoConfig, defaults: WorktreeDefaults) -> WorktreeOptions:
    own = repo.worktree
    if own.folder is not None:
        folder = Path(own.folder).expanduser()
    elif defaults.folder is not None:
        folder = Path(defaults.folder).expanduser() / repo.name
    else:
        folder = claude_worktrees_dir(repo.path)
    return WorktreeOptions(
        folder=folder,
        branch_prefix=defaults.branch_prefix if own.branch_prefix is None else own.branch_prefix,
        clean_merged=defaults.clean_merged if own.clean_merged is None else own.clean_merged,
        submodules=defaults.submodules if own.submodules is None else own.submodules,
    )
