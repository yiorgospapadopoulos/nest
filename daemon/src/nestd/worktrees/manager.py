"""Create, link, set up and remove per-session worktrees; inspect in-place checkouts."""

import asyncio
import logging
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex

from nestd.config.models import RepoConfig
from nestd.errors import ConflictError, InvalidInputError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.hardened import run_checkout_git, run_hardened_git
from nestd.gitops.runner import GitError
from nestd.paths import AppPaths
from nestd.worktrees.setup import LinkResult, SetupResult, link_files, run_commands

BRANCH_PREFIX = "agent/"
MAX_SLUG_LENGTH = 40
SHORT_ID_LENGTH = 8
# New worktrees live where Claude Code keeps its own (D028), named so they are told apart.
WORKTREE_PREFIX = "nest-"
# Worktrees made before the rename to Nest (B43) are still its own.
OWNED_WORKTREE_PREFIXES = (WORKTREE_PREFIX, "harness-")
EXCLUDE_LINE = "/.claude/worktrees/"

logger = logging.getLogger(__name__)


class InvalidBranchError(InvalidInputError):
    pass


class BranchExistsError(ConflictError):
    pass


def claude_worktrees_dir(repo_path: Path) -> Path:
    return repo_path / ".claude" / "worktrees"


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


# Told each worktree path Nest removed, such as to drop its Codex trust entry (B91).
type RemovedHook = Callable[[Path], object]


class WorktreeManager:
    def __init__(
        self,
        paths: AppPaths,
        on_removed: RemovedHook | None = None,
        bus: EventBus | None = None,
    ) -> None:
        """With `bus`, each worktree added or removed is announced as the repo's branches
        changing (B96).
        """
        self._paths = paths
        self._on_removed = on_removed
        self._bus = bus
        # One checkout of an existing branch at a time: of two for the same branch, the
        # second sees the first's worktree and fails (B96).
        self._checking_out = asyncio.Lock()

    async def create(
        self,
        repo: RepoConfig,
        session_id: str,
        title: str,
        branch: str | None = None,
        base: str | None = None,
    ) -> Worktree:
        """A new branch checked out in `<repo>/.claude/worktrees/nest-<short id>`: named
        `branch` (checked with `check_new_branch`) or after the title, starting at commit
        `base` or else at the default branch.

        The worktrees folder is added to the repo's local exclude file first, so neither
        `git status` in the checkout nor a commit picks the worktrees up.
        """
        await _exclude_worktrees(repo)
        name = f"{WORKTREE_PREFIX}{session_id[:SHORT_ID_LENGTH]}"
        path = claude_worktrees_dir(repo.path) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        base = base or await _base_commit(repo)
        branch = branch or branch_name(title)
        await run_checkout_git(["worktree", "add", "-q", "-b", branch, str(path), base], repo.path)
        await self._branches_changed(repo)
        return Worktree(path=path, branch=branch, base_ref=base)

    async def check_out(
        self, repo: RepoConfig, session_id: str, branch: str, base: str
    ) -> Worktree:
        """The existing local branch `branch` checked out in a new worktree at the same
        place as `create`'s (B96); its work is compared with commit `base`. git refuses a
        branch checked out elsewhere already.
        """
        await _exclude_worktrees(repo)
        path = claude_worktrees_dir(repo.path) / f"{WORKTREE_PREFIX}{session_id[:SHORT_ID_LENGTH]}"
        path.parent.mkdir(parents=True, exist_ok=True)
        async with self._checking_out:
            await run_checkout_git(["worktree", "add", "-q", str(path), branch], repo.path)
        await self._branches_changed(repo)
        return Worktree(path=path, branch=branch, base_ref=base)

    async def has_branch(self, repo: RepoConfig, name: str) -> bool:
        """Whether `repo` has the local branch `name`."""
        return await _has_branch(repo, name)

    async def check_new_branch(self, repo: RepoConfig, name: str) -> None:
        """Refuse a name git would not take for a new branch, one an option could be read
        from, or one that exists already (B55).
        """
        problem = InvalidBranchError(f"{name!r} is not a valid branch name")
        if name.startswith("-"):
            raise problem
        try:
            output = await run_hardened_git(["check-ref-format", "--branch", name], repo.path)
        except GitError:
            raise problem from None
        # `@{-1}` and the like are expanded to the branch they stand for.
        if output.strip() != name:
            raise problem
        if await _has_branch(repo, name):
            msg = f"a branch named {name!r} already exists in {repo.name}"
            raise BranchExistsError(msg)

    async def branch_commit(self, repo: RepoConfig, branch: str) -> str:
        """The commit of local branch `branch`, named exactly (no revision syntax)."""
        try:
            output = await run_hardened_git(
                ["show-ref", "--verify", "--hash", f"refs/heads/{branch}"], repo.path
            )
        except GitError:
            msg = f"{repo.name} has no local branch named {branch!r}"
            raise InvalidBranchError(msg) from None
        return output.strip()

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

    async def remove(self, repo: RepoConfig, worktree: Worktree) -> bool:
        """Remove the worktree; close its agent first, so exit hooks cannot recreate files.
        Returns whether it was Nest's own: other worktrees are never touched (B96), such as
        Claude Code's that a chat joined. Its branch always stays: Nest deletes no branch.

        What is already gone (the directory) is skipped, so removing twice is fine.
        Without the repo folder git cannot run; only the leftover directory is deleted.
        """
        if not await asyncio.to_thread(self._owns, repo, worktree.path):
            return False
        has_repo = await asyncio.to_thread(repo.path.is_dir)
        if has_repo and await asyncio.to_thread(_is_worktree, worktree.path):
            await run_hardened_git(["worktree", "remove", "--force", str(worktree.path)], repo.path)
        await asyncio.to_thread(self._delete_leftovers, worktree.path)
        await self._removed(worktree.path)
        if has_repo:
            await run_hardened_git(["worktree", "prune"], repo.path)
        await self._branches_changed(repo)
        return True

    async def _branches_changed(self, repo: RepoConfig) -> None:
        if self._bus is not None:
            await self._bus.publish_ephemeral(types.REPO_BRANCHES_CHANGED, {"name": repo.name})

    async def _removed(self, path: Path) -> None:
        """Bookkeeping: its failure never keeps the worktree from being removed."""
        if self._on_removed is None:
            return
        try:
            await asyncio.to_thread(self._on_removed, path)
        except Exception as error:
            logger.warning("cleaning up after the worktree %s failed (%s)", path, error)

    def _owns(self, repo: RepoConfig, path: Path) -> bool:
        """Whether the worktree is where Nest puts its own: `<repo>/.claude/worktrees/nest-*`
        (`harness-*` before B43), or the data dir's worktrees of earlier versions.
        Claude Code's own worktrees next to them are not.
        """
        target = path.resolve()
        legacy = self._paths.worktrees_dir.resolve()
        return (target.is_relative_to(legacy) and target != legacy) or (
            target.parent == claude_worktrees_dir(repo.path.resolve())
            and target.name.startswith(OWNED_WORKTREE_PREFIXES)
        )

    @staticmethod
    def _delete_leftovers(path: Path) -> None:
        """Delete what remains at a removed worktree's path (one of Nest's own)."""
        target = path.resolve()
        if target.exists():
            shutil.rmtree(target)

    async def head(self, repo: RepoConfig) -> str | None:
        """The checkout's current commit; None in a repository without commits."""
        return await self.head_at(repo.path)

    async def head_at(self, path: Path) -> str | None:
        """The current commit of the checkout or worktree at `path`."""
        try:
            output = await run_hardened_git(["rev-parse", "--verify", "--quiet", "HEAD"], path)
        except GitError:
            return None
        return output.strip()

    async def has_work(self, worktree: Worktree) -> bool:
        """Whether the worktree holds changes (untracked files included) or commits since
        its base. A folder that is gone holds nothing; when git cannot tell, it counts as
        work, so nothing is removed by mistake.
        """
        if not await asyncio.to_thread(worktree.path.is_dir):
            return False
        args = ["status", "--porcelain", "-z", "--ignore-submodules=dirty"]
        try:
            changes = await run_checkout_git(args, worktree.path)
        except GitError:
            return True
        return bool(changes) or await self.head_at(worktree.path) != worktree.base_ref


async def _exclude_worktrees(repo: RepoConfig) -> None:
    """Add EXCLUDE_LINE to the repo's local exclude file unless it is there already."""
    output = await run_hardened_git(["rev-parse", "--git-path", "info/exclude"], repo.path)
    await asyncio.to_thread(_add_exclude_line, repo.path / output.strip())


def _add_exclude_line(exclude: Path) -> None:
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if EXCLUDE_LINE in (line.strip() for line in text.splitlines()):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(f"{text}{EXCLUDE_LINE}\n", encoding="utf-8")


def _is_worktree(path: Path) -> bool:
    return (path / ".git").exists()


async def _has_branch(repo: RepoConfig, branch: str) -> bool:
    try:
        await run_hardened_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], repo.path
        )
    except GitError:
        return False
    return True


async def _base_commit(repo: RepoConfig) -> str:
    try:
        ref = f"refs/heads/{repo.default_branch}^{{commit}}"
        output = await run_hardened_git(["rev-parse", "--verify", "--quiet", ref], repo.path)
    except GitError:
        output = await run_hardened_git(["rev-parse", "HEAD"], repo.path)
    return output.strip()
