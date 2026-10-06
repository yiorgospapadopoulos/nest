"""Create, link, set up and remove per-session worktrees; inspect in-place checkouts."""

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

from harness.config.models import RepoConfig
from harness.gitops.runner import GitError, run_git
from harness.paths import AppPaths
from harness.worktrees.setup import LinkResult, SetupResult, link_files, run_commands

BRANCH_PREFIX = "agent/"
MAX_SLUG_LENGTH = 40
SHORT_ID_LENGTH = 8


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    base_ref: str


def branch_name(title: str) -> str:
    """`agent/<slug>-<6 hex>`, the slug cut at a word boundary to at most 40 characters."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if len(slug) > MAX_SLUG_LENGTH:
        cut = slug[: MAX_SLUG_LENGTH + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else cut[:MAX_SLUG_LENGTH]
    return f"{BRANCH_PREFIX}{slug or 'task'}-{token_hex(3)}"


class WorktreeManager:
    def __init__(self, paths: AppPaths) -> None:
        self._paths = paths

    async def create(self, repo: RepoConfig, session_id: str, title: str) -> Worktree:
        path = self._paths.worktrees_dir / repo.name / session_id[:SHORT_ID_LENGTH]
        path.parent.mkdir(parents=True, exist_ok=True)
        base = await _base_commit(repo)
        branch = branch_name(title)
        await run_git(["worktree", "add", "-q", "-b", branch, str(path), base], repo.path)
        return Worktree(path=path, branch=branch, base_ref=base)

    def link(self, repo: RepoConfig, worktree_path: Path) -> LinkResult:
        return link_files(repo.worktree.link, repo.path, worktree_path)

    async def run_setup(
        self, repo: RepoConfig, worktree_path: Path, session_id: str
    ) -> SetupResult:
        return await run_commands(
            repo.worktree.setup,
            worktree_path,
            self._paths.logs_dir / f"setup-{session_id}.log",
            repo.worktree.setup_timeout_seconds,
        )

    async def remove(self, repo: RepoConfig, worktree: Worktree, delete_branch: bool) -> None:
        """Remove the worktree; close its agent first, so exit hooks cannot recreate files.

        What is already gone (the directory, the branch) is skipped, so removing twice is fine.
        """
        if await asyncio.to_thread(_is_worktree, worktree.path):
            await run_git(["worktree", "remove", "--force", str(worktree.path)], repo.path)
        await asyncio.to_thread(self._delete_leftovers, worktree.path)
        await run_git(["worktree", "prune"], repo.path)
        if delete_branch and await _has_branch(repo, worktree.branch):
            await run_git(["branch", "-D", worktree.branch], repo.path)

    def _delete_leftovers(self, path: Path) -> None:
        """Delete what remains at a removed worktree's path, only inside the worktrees dir."""
        root = self._paths.worktrees_dir.resolve()
        target = path.resolve()
        if target.exists() and target.is_relative_to(root) and target != root:
            shutil.rmtree(target)

    async def head(self, repo: RepoConfig) -> str | None:
        """The checkout's current commit; None in a repository without commits."""
        try:
            output = await run_git(["rev-parse", "--verify", "--quiet", "HEAD"], repo.path)
        except GitError:
            return None
        return output.strip()

    async def dirty_files(self, repo: RepoConfig) -> list[str]:
        """Paths with uncommitted changes, including untracked files, in the main checkout."""
        output = await run_git(["status", "--porcelain", "-z"], repo.path)
        entries = iter(output.split("\0"))
        files: list[str] = []
        for entry in entries:
            if not entry:
                continue
            files.append(entry[3:])
            if entry[0] in "RC":
                next(entries)  # the original path of a rename or copy
        return sorted(files)


def _is_worktree(path: Path) -> bool:
    return (path / ".git").exists()


async def _has_branch(repo: RepoConfig, branch: str) -> bool:
    try:
        await run_git(["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], repo.path)
    except GitError:
        return False
    return True


async def _base_commit(repo: RepoConfig) -> str:
    try:
        ref = f"refs/heads/{repo.default_branch}^{{commit}}"
        output = await run_git(["rev-parse", "--verify", "--quiet", ref], repo.path)
    except GitError:
        output = await run_git(["rev-parse", "HEAD"], repo.path)
    return output.strip()
