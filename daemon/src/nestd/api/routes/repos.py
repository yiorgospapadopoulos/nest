from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from nestd.api.deps import Context, RequireDevice
from nestd.config.models import Color, Mascot
from nestd.repos.branch_map import BranchMap, read_branch_map
from nestd.repos.service import RepoView
from nestd.sessions.commands import CommandList
from nestd.sessions.repo_removal import remove_repo

router = APIRouter(prefix="/api/repos", dependencies=[RequireDevice])


class RegisterRepo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    # Defaults to the folder name.
    name: str | None = None


# A URL git accepts: scheme://..., scp-like `[user@]host:path`, or an absolute path.
_GIT_URL = r"^([A-Za-z][A-Za-z0-9+.-]*://\S+|([^@\s/:]+@)?[^\s/:]+:\S+|/\S+)$"


class UpdateRepo(BaseModel):
    """Project settings to set. `link` and `setup` left out (or null) are unchanged;
    `default`, `icon` and `icon_color` left out are unchanged, and null clears them
    (BUG-102, B36).
    """

    model_config = ConfigDict(extra="forbid")

    # Whether new chats use a worktree; null follows `[agents] default_mode` (D038).
    default: bool | None = None
    # Gitignored files symlinked into each new worktree, relative to the repository.
    link: list[str] | None = None
    # Commands run in each new worktree after it is created.
    setup: list[str] | None = None
    # A pixie sprite as the project's icon; null shows its initials.
    icon: Mascot | None = None
    # A pixie colour for the icon; null is the default colour.
    icon_color: Color | None = None
    # Git repos only (422 otherwise): an existing local branch (D104).
    default_branch: str | None = None
    # Git repos only: the only URL Nest pushes origin to (D050); null clears it, so the
    # next push asks the user to confirm origin's URL.
    remote_url: Annotated[str, StringConstraints(pattern=_GIT_URL)] | None = None
    # How long each setup command may run in a new worktree.
    setup_timeout_seconds: Annotated[int, Field(ge=1, le=86400)] | None = None

    def changes(self) -> dict[str, object]:
        sent = self.model_dump(exclude_unset=True)
        return {key: value for key, value in sent.items() if value is not None or key in _CLEARABLE}


_CLEARABLE = frozenset({"default", "icon", "icon_color", "remote_url"})


class RepoOrder(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Project names in the new order; unknown names are ignored, left out ones follow.
    order: list[str]


@router.get("")
async def list_repos(ctx: Context) -> list[RepoView]:
    """Plain folders that became git repositories are updated on the way (D041)."""
    return [await ctx.repos.view(repo) for repo in await ctx.repos.list_current()]


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_repo(body: RegisterRepo, ctx: Context) -> RepoView:
    return await ctx.repos.view(await ctx.repos.register(body.path, body.name))


@router.put("/order")
async def reorder_repos(body: RepoOrder, ctx: Context) -> list[RepoView]:
    """Save the project order clients show (D090); announced as `repos.reordered`."""
    return [await ctx.repos.view(repo) for repo in await ctx.repos.reorder(body.order)]


@router.get("/{name}")
async def get_repo(name: str, ctx: Context) -> RepoView:
    return await ctx.repos.view(await ctx.repos.current(name))


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def unregister_repo(name: str, ctx: Context, purge_sessions: bool = False) -> Response:
    """Unregister the repo; with purge_sessions, delete its sessions first. The folder stays."""
    await remove_repo(
        name, purge_sessions=purge_sessions, repos=ctx.repos, sessions=ctx.sessions, bus=ctx.bus
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{name}/commands")
async def repo_commands(name: str, ctx: Context) -> CommandList:
    """The slash commands and agents the repo's latest agent run reported, for new chats."""
    ctx.repos.get(name)
    return await ctx.commands.for_repo(name)


class BranchList(BaseModel):
    branches: list[str]


@router.get("/{name}/branches")
async def repo_branches(name: str, ctx: Context) -> BranchList:
    """Local branch names, sorted: where a new worktree chat can start from (B55)."""
    return BranchList(branches=await ctx.repos.branches(name))


@router.get("/{name}/branch-map")
async def repo_branch_map(name: str, ctx: Context) -> BranchMap:
    """The default branch, the project folder's branch and the branches of linked
    worktrees, each with the branch it comes from (B96); `repo.branches_changed` says when
    to read it again.
    """
    repo = await ctx.repos.git_repo(name)
    return await read_branch_map(repo, await ctx.sessions.worktree_bases(name))


@router.get("/{name}/link-suggestions")
async def link_suggestions(name: str, ctx: Context) -> list[str]:
    """Gitignored files in the checkout worth adding to `worktree.link`."""
    return await ctx.repos.suggest_links(name)


@router.patch("/{name}")
async def update_repo(name: str, body: UpdateRepo, ctx: Context) -> RepoView:
    """Edit the worktree default, links, setup and its time limit (IMP-09, BUG-102), the
    icon (B36), the default branch and push URL (D104); 422 for a link outside the
    repository, an unknown branch, or git settings of a plain folder. Announced as
    `repo.updated`.
    """
    return await ctx.repos.view(await ctx.repos.edit(name, body.changes()))
