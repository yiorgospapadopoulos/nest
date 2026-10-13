from pathlib import Path

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from harness.api.deps import Context, RequireDevice
from harness.config.models import RepoConfig, WorktreeConfig
from harness.sessions.commands import CommandList
from harness.sessions.repo_removal import remove_repo

router = APIRouter(prefix="/api/repos", dependencies=[RequireDevice])


class RegisterRepo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: Path
    # Defaults to the folder name.
    name: str | None = None


class UpdateRepo(BaseModel):
    """`[worktree]` keys to set; those left out (or null) are unchanged."""

    model_config = ConfigDict(extra="forbid")

    # Gitignored files symlinked into each new worktree, relative to the repository.
    link: list[str] | None = None
    # Commands run in each new worktree after it is created.
    setup: list[str] | None = None


@router.get("")
async def list_repos(ctx: Context) -> list[RepoConfig]:
    """Plain folders that became git repositories are updated on the way (D041)."""
    return await ctx.repos.list_current()


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_repo(body: RegisterRepo, ctx: Context) -> RepoConfig:
    return await ctx.repos.register(body.path, body.name)


@router.get("/{name}")
async def get_repo(name: str, ctx: Context) -> RepoConfig:
    return await ctx.repos.current(name)


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


@router.get("/{name}/link-suggestions")
async def link_suggestions(name: str, ctx: Context) -> list[str]:
    """Gitignored files in the checkout worth adding to `worktree.link`."""
    return await ctx.repos.suggest_links(name)


@router.patch("/{name}")
async def update_repo(name: str, body: UpdateRepo, ctx: Context) -> RepoConfig:
    """Edit links and setup (IMP-09); 422 for a link outside the repository. Announced as
    `repo.updated`.
    """
    return await ctx.repos.edit_worktree(name, body.model_dump(exclude_none=True))


@router.put("/{name}/worktree")
async def update_worktree(name: str, body: WorktreeConfig, ctx: Context) -> RepoConfig:
    """Replace the whole `[worktree]` config; announced as `repo.updated`."""
    return await ctx.repos.configure_worktree(name, body)
