"""Create, link, set up and remove per-session worktrees; inspect in-place checkouts."""

import asyncio
import contextlib
import logging
import re
import shutil
from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from secrets import token_hex
from typing import Protocol

from nestd.config.models import RepoConfig, WorktreeDefaults
from nestd.errors import ConflictError, InvalidInputError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.hardened import remote_names, run_checkout_git, run_hardened_git
from nestd.gitops.runner import GitError
from nestd.paths import AppPaths
from nestd.repos.service import RepoUnreadableError
from nestd.worktrees.at_risk import AtRisk, at_risk
from nestd.worktrees.options import (
    SUBMODULES_COMMAND,
    WorktreeOptions,
    options_for,
)
from nestd.worktrees.ownership import WORKTREE_PREFIX, is_nest_worktree, mark
from nestd.worktrees.setup import LinkResult, SetupResult, link_files, run_commands

BRANCH_PREFIX = "agent/"
MAX_SLUG_LENGTH = 40
SHORT_ID_LENGTH = 8
# What `git branch -d` says when it refuses a branch with work it cannot find elsewhere.
NOT_MERGED = "not fully merged"
# What `git worktree add` says of a branch checked out elsewhere, naming where.
USED_AT = re.compile(r"already used by worktree at '(.+)'")

logger = logging.getLogger(__name__)


class InvalidBranchError(InvalidInputError):
    pass


class BranchExistsError(ConflictError):
    pass


@dataclass(frozen=True)
class Worktree:
    path: Path
    branch: str
    base_ref: str


def branch_name(title: str, prefix: str = BRANCH_PREFIX) -> str:
    """`<prefix><slug>-<6 hex>`, such as `agent/fix-login-1a2b3c`, the slug cut at a word
    boundary to at most 40 characters.
    """
    return f"{prefix}{_slug(title) or 'task'}-{token_hex(3)}"


def issue_branch_name(number: int, title: str) -> str:
    """GitHub's own name for an issue's branch, `<number>-<slug>` (B101)."""
    slug = _slug(title)
    return f"{number}-{slug}" if slug else str(number)


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    if len(slug) > MAX_SLUG_LENGTH:
        cut = slug[: MAX_SLUG_LENGTH + 1]
        slug = cut.rsplit("-", 1)[0] if "-" in cut else cut[:MAX_SLUG_LENGTH]
    return slug


# Told each worktree path Nest removed, such as to drop its Codex trust entry (B91).
type RemovedHook = Callable[[Path], object]


class WorktreeRuns(Protocol):
    """A worktree's ports and dev server run (B108)."""

    async def setup_env(self, repo: RepoConfig, folder: Path) -> Mapping[str, str]:
        """The variables its setup commands get, such as its ports."""
        ...

    async def set_up(self, repo: RepoConfig, folder: Path) -> None:
        """Its setup succeeded."""
        ...

    async def removing(self, folder: Path) -> None:
        """Nest is about to remove it."""
        ...


class WorktreeManager:
    def __init__(
        self,
        paths: AppPaths,
        on_removed: RemovedHook | None = None,
        bus: EventBus | None = None,
        runs: WorktreeRuns | None = None,
        defaults: Callable[[], WorktreeDefaults] = WorktreeDefaults,
    ) -> None:
        """With `bus`, each worktree added or removed is announced as the repo's branches
        changing (B96). `runs` gives setup commands the worktree's ports, starts its run
        after setup and stops it before it is removed (B108). `defaults` reads the
        `[worktrees]` settings as they are now (B141).
        """
        self._defaults = defaults
        self._runs = runs
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
        folder: str | None = None,
    ) -> Worktree:
        """A new branch checked out in `nest-<short id>` in the project's worktrees folder
        (`options`), or in `folder` there (`free_folder`, for a chat's further worktrees):
        named `branch` (checked with `check_new_branch`) or after the title, starting at
        commit `base` or else at the default branch.

        A worktrees folder inside the project is added to the repo's local exclude file
        first, so neither `git status` in the checkout nor a commit picks the worktrees up.
        """
        options = self.options(repo)
        await _exclude_worktrees(repo, options.folder)
        name = folder or f"{WORKTREE_PREFIX}{session_id[:SHORT_ID_LENGTH]}"
        path = options.folder / name
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        base = base or await _base_commit(repo)
        branch = branch or branch_name(title, options.branch_prefix)
        await run_checkout_git(["worktree", "add", "-q", "-b", branch, str(path), base], repo.path)
        await mark(path)
        await self._branches_changed(repo)
        return Worktree(path=path, branch=branch, base_ref=base)

    async def check_out(
        self, repo: RepoConfig, session_id: str, branch: str, base: str
    ) -> Worktree:
        """The existing local branch `branch` checked out in a new worktree at the same
        place as `create`'s (B96); its work is compared with commit `base`. git refuses a
        branch checked out elsewhere already.
        """
        folder = self.options(repo).folder
        await _exclude_worktrees(repo, folder)
        path = folder / f"{WORKTREE_PREFIX}{session_id[:SHORT_ID_LENGTH]}"
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        async with self._checking_out:
            await _add_worktree(repo, path, branch)
        await mark(path)
        await self._branches_changed(repo)
        return Worktree(path=path, branch=branch, base_ref=base)

    def free_folder(self, repo: RepoConfig, session_id: str, taken: Collection[str]) -> str:
        """A folder name for the chat's next worktree: Nest's own (`nest-<short id>`, then
        `-2`, `-3` and so on) that is not on disk and not in `taken`, names it had before.
        """
        base = f"{WORKTREE_PREFIX}{session_id[:SHORT_ID_LENGTH]}"
        folder = self.options(repo).folder
        name, number = base, 1
        while name in taken or (folder / name).exists():
            number += 1
            name = f"{base}-{number}"
        return name

    def options(self, repo: RepoConfig) -> WorktreeOptions:
        """The project's worktree choices as the settings are now (B141)."""
        return options_for(repo, self._defaults())

    async def has_branch(self, repo: RepoConfig, name: str) -> bool:
        """Whether `repo` has the local branch `name`."""
        return await _has_branch(repo, name)

    async def free_branch(self, repo: RepoConfig, name: str) -> str:
        """`name`, or with `-2`, `-3` and so on when a branch has it already, here or on
        origin, as a teammate may have pushed one (B101).
        """
        taken = await _origin_branches(repo)
        candidate, number = name, 1
        while candidate in taken or await _has_branch(repo, candidate):
            number += 1
            candidate = f"{name}-{number}"
        return candidate

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

    async def track_remote(self, repo: RepoConfig, remote: str, name: str) -> str:
        """A local branch `name` tracking the one of that name on `remote`, with nothing
        checked out. Accepted when it exists already at the same commit, as after a double
        click. Not `git branch --track`, which refuses a branch outside the remote's
        configured refspec, as on a single-branch clone.
        """
        try:
            remotes = await remote_names(repo.path)
        except GitError as error:
            raise RepoUnreadableError(error) from None
        if remote not in remotes:
            msg = f"{repo.name} has no remote named {remote!r}"
            raise InvalidInputError(msg)
        if name.startswith("refs/"):
            msg = f"{name!r} is not a valid branch name"
            raise InvalidBranchError(msg)
        with contextlib.suppress(BranchExistsError):
            await self.check_new_branch(repo, name)
        ref = f"refs/remotes/{remote}/{name}"
        try:
            output = await run_hardened_git(["show-ref", "--verify", "--hash", ref], repo.path)
        except GitError:
            msg = f"{remote} has no branch named {name!r}"
            raise InvalidBranchError(msg) from None
        # Read from the refs as stored and compared blind to case on every system: on a
        # case-insensitive disk `git branch Case` would write over `case`, and asking git
        # for `Case` by name does not find a packed `case` first.
        heads = await _exact_heads(repo)
        if name in heads:
            if heads[name] == output.strip():
                return name
            msg = f"a branch named {name!r} already exists in {repo.name}"
            raise BranchExistsError(msg)
        if any(head.casefold() == name.casefold() for head in heads):
            msg = f"{name!r} differs only in case from a local branch of {repo.name}"
            raise BranchExistsError(msg)
        try:
            await run_hardened_git(["branch", "--no-track", name, ref], repo.path)
        except GitError as error:
            raise ConflictError(error.stderr.strip().splitlines()[0]) from None
        await run_hardened_git(["config", f"branch.{name}.remote", remote], repo.path)
        await run_hardened_git(["config", f"branch.{name}.merge", f"refs/heads/{name}"], repo.path)
        await self._branches_changed(repo)
        return name

    def link(self, repo: RepoConfig, worktree_path: Path) -> LinkResult:
        return link_files(repo.worktree.link, repo.path, worktree_path)

    async def run_setup(
        self, repo: RepoConfig, worktree_path: Path, session_id: str
    ) -> SetupResult:
        runs = self._runs
        submodules = self.options(repo).submodules and await asyncio.to_thread(
            (worktree_path / ".gitmodules").is_file
        )
        result = await run_commands(
            [SUBMODULES_COMMAND, *repo.worktree.setup] if submodules else repo.worktree.setup,
            worktree_path,
            self._paths.logs_dir / f"setup-{session_id}.log",
            repo.worktree.setup_timeout_seconds,
            None if runs is None else await runs.setup_env(repo, worktree_path),
        )
        if result.ok and runs is not None:
            await runs.set_up(repo, worktree_path)
        return result

    async def remove(self, repo: RepoConfig, worktree: Worktree) -> bool:
        """Remove the worktree; close its agent first, so exit hooks cannot recreate files.
        Returns whether it was Nest's own: other worktrees are never touched (B96), such as
        Claude Code's that a chat joined. Its branch stays; only `delete_branch`, when a
        chat's agent asks for it, deletes one.

        What is already gone (the directory) is skipped, so removing twice is fine.
        Without the repo folder git cannot run; only the leftover directory is deleted.
        """
        if not await asyncio.to_thread(self.owns, repo, worktree.path):
            return False
        await self._removing(worktree.path)
        has_repo = await asyncio.to_thread(repo.path.is_dir)
        if has_repo and await asyncio.to_thread(_is_worktree, worktree.path):
            await run_hardened_git(["worktree", "remove", "--force", str(worktree.path)], repo.path)
        await asyncio.to_thread(self._delete_leftovers, worktree.path)
        await self._removed(worktree.path)
        if has_repo:
            await run_hardened_git(["worktree", "prune"], repo.path)
        await self._branches_changed(repo)
        return True

    async def delete_branch(self, repo: RepoConfig, branch: str) -> str | None:
        """Delete the local branch the way `git branch -d` does, only when git finds it
        merged (B127); never the default branch or the one the project folder is on.
        Returns None once it is gone, else why it stays.
        """
        here = await _current_branch(repo)
        if branch == repo.default_branch:
            return "it is the project's default branch"
        if branch == here:
            return "the project folder is on it"
        try:
            await run_hardened_git(["branch", "-d", "--", branch], repo.path)
        except GitError as error:
            if NOT_MERGED in error.stderr:
                return f"not merged into {await _merge_target(repo, branch) or here or 'HEAD'}"
            return error.stderr.strip().splitlines()[0] if error.stderr.strip() else str(error)
        await self._branches_changed(repo)
        return None

    async def _branches_changed(self, repo: RepoConfig) -> None:
        if self._bus is not None:
            await self._bus.publish_ephemeral(types.REPO_BRANCHES_CHANGED, {"name": repo.name})

    async def _removing(self, path: Path) -> None:
        """Stop its run first (B108); a failure never keeps the worktree from being removed."""
        if self._runs is None:
            return
        try:
            await self._runs.removing(path)
        except Exception as error:
            logger.warning("stopping the run in the worktree %s failed (%s)", path, error)

    async def _removed(self, path: Path) -> None:
        """Bookkeeping: its failure never keeps the worktree from being removed."""
        if self._on_removed is None:
            return
        try:
            await asyncio.to_thread(self._on_removed, path)
        except Exception as error:
            logger.warning("cleaning up after the worktree %s failed (%s)", path, error)

    def owns(self, repo: RepoConfig, path: Path) -> bool:
        """Whether the worktree is Nest's own (`is_nest_worktree`), or one of the data dir's
        worktrees of earlier versions. Claude Code's own worktrees next to them are not.
        Blocks.
        """
        target = path.resolve()
        legacy = self._paths.worktrees_dir.resolve()
        return (target.is_relative_to(legacy) and target != legacy) or is_nest_worktree(
            repo.path, target
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

    async def at_risk(self, repo: RepoConfig, worktree: Worktree) -> AtRisk:
        """What removing the worktree would lose (B141): its changes, untracked files and
        commits not on the project's default branch, or else not on the commit it started
        from. A folder that is gone holds nothing. Raises GitError when git cannot tell.
        """
        if not await asyncio.to_thread(worktree.path.is_dir):
            return AtRisk(None)
        branch = repo.default_branch
        if branch is not None and await _has_branch(repo, branch):
            return await at_risk(worktree.path, f"refs/heads/{branch}", branch)
        base = worktree.base_ref or None
        return await at_risk(worktree.path, base, base and base[:SHORT_ID_LENGTH])

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


def held_at(error: GitError) -> Path | None:
    """The checkout `git worktree add` says holds the branch, if that is why it refused."""
    found = USED_AT.search(error.stderr)
    return None if found is None else Path(found[1])


async def _add_worktree(repo: RepoConfig, path: Path, branch: str) -> None:
    """`branch` checked out at `path`. A folder deleted by hand leaves a record that still
    holds the branch: only then is that one record dropped. Others stay, as their folders
    may only be moved away; a real checkout and a locked worktree still refuse.
    """
    args = ["worktree", "add", "-q", "--", str(path), branch]
    try:
        await run_checkout_git(args, repo.path)
    except GitError as error:
        held = held_at(error)
        if held is None or await asyncio.to_thread(held.exists):
            raise
        try:
            await run_hardened_git(["worktree", "remove", "--force", "--", str(held)], repo.path)
        except GitError:
            raise error from None
        await run_checkout_git(args, repo.path)
    if branch.startswith("-"):
        # git takes such a name for a commit and detaches: commits would land on no branch.
        await run_hardened_git(["symbolic-ref", "HEAD", f"refs/heads/{branch}"], path)


async def _exclude_worktrees(repo: RepoConfig, folder: Path) -> None:
    """Add the worktrees folder to the repo's local exclude file unless it is there already
    or outside the project, such as `/.claude/worktrees/`.
    """
    inside = await asyncio.to_thread(_inside, repo.path, folder)
    if inside is None:
        return
    output = await run_hardened_git(["rev-parse", "--git-path", "info/exclude"], repo.path)
    await asyncio.to_thread(_add_exclude_line, repo.path / output.strip(), f"/{inside}/")


def _inside(repo_path: Path, folder: Path) -> str | None:
    """The folder relative to the project, if it is in it."""
    target, root = folder.resolve(), repo_path.resolve()
    if target == root or not target.is_relative_to(root):
        return None
    return target.relative_to(root).as_posix()


def _add_exclude_line(exclude: Path, line: str) -> None:
    text = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    if line in (existing.strip() for existing in text.splitlines()):
        return
    if text and not text.endswith("\n"):
        text += "\n"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(f"{text}{line}\n", encoding="utf-8")


def _is_worktree(path: Path) -> bool:
    return (path / ".git").exists()


async def _origin_branches(repo: RepoConfig) -> set[str]:
    """The branch names on origin; none when it cannot be reached, such as offline."""
    try:
        listing = await run_hardened_git(["ls-remote", "--heads", "origin"], repo.path)
    except GitError as error:
        logger.warning(
            "could not list origin's branches of %s (%s)", repo.name, type(error).__name__
        )
        return set()
    # Lines of `<sha><tab>refs/heads/<name>`.
    return {line.split("\t", 1)[-1].removeprefix("refs/heads/") for line in listing.splitlines()}


async def _has_branch(repo: RepoConfig, branch: str) -> bool:
    try:
        await run_hardened_git(
            ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"], repo.path
        )
    except GitError:
        return False
    return True


async def _exact_heads(repo: RepoConfig) -> dict[str, str]:
    """Each local branch's commit, by the name as it is stored."""
    output = await run_hardened_git(
        ["for-each-ref", "--format=%(objectname) %(refname:lstrip=2)", "refs/heads/"], repo.path
    )
    return {name: commit for commit, name in (line.split(" ", 1) for line in output.splitlines())}


async def _current_branch(repo: RepoConfig) -> str | None:
    """The branch the project folder is on; None on a detached HEAD."""
    try:
        output = await run_hardened_git(["symbolic-ref", "--quiet", "--short", "HEAD"], repo.path)
    except GitError:
        return None
    return output.strip() or None


async def _merge_target(repo: RepoConfig, branch: str) -> str | None:
    """The upstream `git branch -d` compares a branch with instead of HEAD, if it has one."""
    args = ["for-each-ref", "--format=%(upstream:short)", f"refs/heads/{branch}"]
    try:
        return (await run_hardened_git(args, repo.path)).strip() or None
    except GitError:
        return None


async def _base_commit(repo: RepoConfig) -> str:
    try:
        ref = f"refs/heads/{repo.default_branch}^{{commit}}"
        output = await run_hardened_git(["rev-parse", "--verify", "--quiet", ref], repo.path)
    except GitError:
        output = await run_hardened_git(["rev-parse", "HEAD"], repo.path)
    return output.strip()
