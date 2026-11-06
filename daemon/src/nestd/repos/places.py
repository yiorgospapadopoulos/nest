"""Each project's selected place (B131): where new chats start until the user clicks
somewhere else. It only ever changes what a new chat's composer offers: nothing here moves
a chat or the project folder.
"""

import asyncio
from collections.abc import Sequence
from pathlib import Path

from nestd.config.models import RepoConfig
from nestd.errors import InvalidInputError
from nestd.gitops.hardened import run_hardened_git
from nestd.gitops.runner import GitError
from nestd.repos.branch_map import Checkout, checkouts
from nestd.repos.service import BRANCH_REF, PlaceReading, RepoUnreadableError, SelectedPlace
from nestd.storage.db import Database


class InvalidPlaceError(InvalidInputError):
    pass


class PlaceBook:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def current(self, repo: RepoConfig) -> PlaceReading:
        """The repo's selected place. One that is gone is marked so here, and only here, so
        "gone" has one meaning, and it stays reported, however often this is read and even
        if the branch comes back, until `select` or `forget`: no client may have been
        watching when it went. A worktree that moved to another branch stays selected, with
        that branch's name. When git cannot read the repo nothing is known to be gone.

        Stored changes name what was read, so a click made meanwhile stays.
        """
        row = await self._db.fetch_one(
            "SELECT branch, worktree_path, gone FROM selected_places WHERE repo = ?", (repo.name,)
        )
        if row is None:
            return PlaceReading()
        if row["gone"]:
            return PlaceReading(gone=row["branch"])
        stored = SelectedPlace(branch=row["branch"], worktree_path=row["worktree_path"])
        try:
            place = await _still_there(repo, stored)
        except GitError:
            return PlaceReading(stored)
        same_row = (repo.name, row["branch"], row["worktree_path"])
        if place is None:
            await self._db.execute(
                "UPDATE selected_places SET gone = 1"
                " WHERE repo = ? AND branch = ? AND worktree_path IS ?",
                same_row,
            )
            return PlaceReading(gone=row["branch"])
        if place != stored:
            await self._db.execute(
                "UPDATE selected_places SET branch = ?"
                " WHERE repo = ? AND branch = ? AND worktree_path IS ?",
                (place.branch, *same_row),
            )
        return PlaceReading(place)

    async def select(self, repo: RepoConfig, branch: str | None, worktree: Path | None) -> None:
        """Select a local branch, or a linked worktree on a branch; neither clears it. Any
        of these also clears a place reported gone. 409 when git cannot read the repo.
        """
        if branch is not None and worktree is not None:
            msg = "choose a branch or a worktree, not both"
            raise InvalidPlaceError(msg)
        try:
            if branch is not None:
                if not await _has_branch(repo, branch):
                    msg = f"{repo.name} has no local branch named {branch!r}"
                    raise InvalidPlaceError(msg)
                await self._save(repo.name, SelectedPlace(branch=branch))
            elif worktree is not None:
                await self._save(repo.name, await _on_branch(repo, worktree))
            else:
                await self.forget(repo.name)
        except GitError as error:
            raise RepoUnreadableError(error) from None

    async def forget_gone(self, repo: str) -> None:
        """Clear a place reported gone and nothing else: a selection made meanwhile stays."""
        await self._db.execute("DELETE FROM selected_places WHERE repo = ? AND gone = 1", (repo,))

    async def forget(self, repo: str) -> None:
        await self._db.execute("DELETE FROM selected_places WHERE repo = ?", (repo,))

    async def _save(self, repo: str, place: SelectedPlace) -> None:
        await self._db.execute(
            "INSERT INTO selected_places (repo, branch, worktree_path) VALUES (?, ?, ?)"
            " ON CONFLICT (repo) DO UPDATE"
            " SET branch = excluded.branch, worktree_path = excluded.worktree_path, gone = 0",
            (
                repo,
                place.branch,
                None if place.worktree_path is None else str(place.worktree_path),
            ),
        )


async def _still_there(repo: RepoConfig, place: SelectedPlace) -> SelectedPlace | None:
    if place.worktree_path is None:
        return place if await _has_branch(repo, place.branch) else None
    found = await _linked(repo, place.worktree_path)
    if found is None or found.branch is None:
        return None
    return SelectedPlace(branch=found.branch, worktree_path=place.worktree_path)


async def _has_branch(repo: RepoConfig, branch: str) -> bool:
    """Unlike `show-ref`, a missing branch is told from git failing: no line, no error. The
    pattern also matches what is under it, so the line must be the branch itself.
    """
    ref = f"{BRANCH_REF}{branch}"
    output = await run_hardened_git(["for-each-ref", "--format=%(refname)", ref], repo.path)
    return ref in output.split("\n")


async def _on_branch(repo: RepoConfig, path: Path) -> SelectedPlace:
    found = await _linked(repo, path)
    if found is None:
        msg = f"{path} is not a linked worktree of {repo.name}"
        raise InvalidPlaceError(msg)
    if found.branch is None:
        msg = f"the worktree {path} is not on a branch"
        raise InvalidPlaceError(msg)
    return SelectedPlace(branch=found.branch, worktree_path=found.path)


async def _linked(repo: RepoConfig, path: Path) -> Checkout | None:
    """The linked worktree at `path`, however either path is spelled."""
    _, *linked = await checkouts(repo.path)
    return await asyncio.to_thread(_at, path, linked)


def _at(path: Path, linked: Sequence[Checkout]) -> Checkout | None:
    target = path.resolve()
    return next((checkout for checkout in linked if checkout.path.resolve() == target), None)
