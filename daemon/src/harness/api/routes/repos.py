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


@router.get("")
async def list_repos(ctx: Context) -> list[RepoConfig]:
    return ctx.repos.list_repos()


@router.post("", status_code=status.HTTP_201_CREATED)
async def register_repo(body: RegisterRepo, ctx: Context) -> RepoConfig:
    return await ctx.repos.register(body.path, body.name)


@router.get("/{name}")
async def get_repo(name: str, ctx: Context) -> RepoConfig:
    return ctx.repos.get(name)


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


@router.put("/{name}/worktree")
async def update_worktree(name: str, body: WorktreeConfig, ctx: Context) -> RepoConfig:
    return ctx.repos.update_worktree_config(name, body)
