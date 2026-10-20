"""A new chat in an existing linked worktree of its project, or on an existing local branch
(B96): where it works, and the commit its work is compared with.
"""

import asyncio
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

from nestd.config.models import RepoConfig
from nestd.errors import InvalidInputError
from nestd.gitops.hardened import run_hardened_git
from nestd.gitops.runner import GitError
from nestd.repos.branch_map import checkouts, read_branch_map
from nestd.repos.service import BRANCH_REF
from nestd.sessions.models import SessionMode
from nestd.worktrees.manager import Worktree, WorktreeManager


@dataclass(frozen=True)
class Place:
    """Where a new chat works: in place, in the existing `worktree`, or (with neither) in a
    new worktree of Nest's with `branch` checked out.
    """

    mode: SessionMode
    base_ref: str | None
    branch: str | None = None
    worktree: Worktree | None = None


async def place_on_branch(
    repo: RepoConfig, name: str, bases: Mapping[Path, str], worktrees: WorktreeManager
) -> Place:
    """A chat on the local branch `name` of a git repo: in place when the project folder
    is on it, in the linked worktree that has it checked out, else in a new worktree.
    """
    commit = await worktrees.branch_commit(repo, name)
    main, *linked = await checkouts(repo.path)
    if main.branch == name:
        return Place("in_place", await worktrees.head(repo))
    found = next((checkout.path for checkout in linked if checkout.branch == name), None)
    if found is not None:
        return await join_place(repo, found, bases, worktrees)
    base = await _fork_point(repo, name, bases) or commit
    return Place("worktree", base, branch=name)


async def join_place(
    repo: RepoConfig, path: Path, bases: Mapping[Path, str], worktrees: WorktreeManager
) -> Place:
    """A chat joining the linked worktree at `path` (see `join_worktree`)."""
    worktree = await join_worktree(repo, path, bases, worktrees)
    return Place("worktree", worktree.base_ref, branch=worktree.branch, worktree=worktree)


async def join_worktree(
    repo: RepoConfig, path: Path, bases: Mapping[Path, str], worktrees: WorktreeManager
) -> Worktree:
    """The linked worktree of `repo` at `path` (not its main checkout), whose folder
    exists and which is on a branch. Its path is as git lists it.

    Its base is the one a chat on it recorded already (`bases`, by worktree path), so all
    of its chats compare the same work; else where its branch forks from its parent in
    the branch map, else from the default branch; else its current commit.
    """
    if not path.is_absolute():
        msg = "worktree_path must be an absolute path"
        raise InvalidInputError(msg)
    if not await asyncio.to_thread(path.is_dir):
        msg = f"the folder {path} does not exist"
        raise InvalidInputError(msg)
    target = await asyncio.to_thread(path.resolve)
    _, *linked = await checkouts(repo.path)
    found = await asyncio.to_thread(_matching, target, ((c.path, c.branch) for c in linked))
    if found is None:
        msg = f"{path} is not a linked worktree of {repo.name}"
        raise InvalidInputError(msg)
    worktree_path, branch = found
    if branch is None:
        msg = f"the worktree {path} is not on a branch"
        raise InvalidInputError(msg)
    recorded = await asyncio.to_thread(_matching, target, bases.items())
    if recorded is not None:
        return Worktree(worktree_path, branch, recorded[1])
    base = await _fork_point(repo, branch, bases) or await worktrees.head_at(worktree_path)
    assert base is not None  # noqa: S101 (a worktree on a branch has a commit)
    return Worktree(worktree_path, branch, base)


async def linked_checkout(repo: RepoConfig, branch: str) -> Path | None:
    """The linked worktree that has `branch` checked out, if one does."""
    _, *linked = await checkouts(repo.path)
    return next((checkout.path for checkout in linked if checkout.branch == branch), None)


async def _fork_point(repo: RepoConfig, branch: str, bases: Mapping[Path, str]) -> str | None:
    """Where `branch` forks from its parent in the branch map, else from the default
    branch; None when neither can tell.
    """
    branch_map = await read_branch_map(repo, bases)
    parent = next((b.parent for b in branch_map.branches if b.name == branch), None)
    for other in (parent, repo.default_branch):
        if other is None:
            continue
        try:
            output = await run_hardened_git(
                ["merge-base", f"{BRANCH_REF}{branch}", f"{BRANCH_REF}{other}"], repo.path
            )
        except GitError:
            continue
        return output.strip()
    return None


def _matching[T](target: Path, entries: Iterable[tuple[Path, T]]) -> tuple[Path, T] | None:
    """The first entry whose path is `target` once resolved."""
    return next(((path, value) for path, value in entries if path.resolve() == target), None)
