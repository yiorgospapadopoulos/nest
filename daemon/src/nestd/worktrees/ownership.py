"""Which worktrees are Nest's own (B96): it removes only those.

Nest marks each worktree it makes in the worktree's own folder inside the repository's
`.git` (B141), which git keeps out of every checkout, so the mark holds wherever the
worktree's folder is. Worktrees made before the mark are known by their place: a
`nest-*` folder (`harness-*` before B43) in `<repo>/.claude/worktrees`.
"""

import asyncio
from pathlib import Path

from nestd.gitops.hardened import run_hardened_git
from nestd.worktrees.options import claude_worktrees_dir

WORKTREE_PREFIX = "nest-"
OWNED_WORKTREE_PREFIXES = (WORKTREE_PREFIX, "harness-")
MARKER = "nest-worktree"
_GITDIR = "gitdir:"


async def mark(path: Path) -> None:
    """Mark the worktree at `path` as Nest's."""
    gitdir = Path((await run_hardened_git(["rev-parse", "--absolute-git-dir"], path)).strip())
    await asyncio.to_thread((gitdir / MARKER).write_text, "Made by Nest\n", encoding="utf-8")


def is_nest_worktree(repo_path: Path, path: Path) -> bool:
    """Whether the worktree at `path` of the project at `repo_path` is Nest's. Blocks."""
    target = path.resolve()
    if target.parent == claude_worktrees_dir(repo_path.resolve()) and target.name.startswith(
        OWNED_WORKTREE_PREFIXES
    ):
        return True
    gitdir = _gitdir(target)
    return gitdir is not None and (gitdir / MARKER).is_file()


def _gitdir(worktree: Path) -> Path | None:
    """The worktree's own folder in the repository's `.git`, from its `.git` file."""
    try:
        text = (worktree / ".git").read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith(_GITDIR):
        return None
    # git writes it relative to the worktree with `worktree.useRelativePaths`.
    return (worktree / text.removeprefix(_GITDIR).strip()).resolve()
