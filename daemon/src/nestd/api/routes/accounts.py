"""Accounts in Settings (D104): Claude through Claude Code's own `claude auth` commands,
GitHub through the user's `gh` login. No token is ever read or returned."""

from fastapi import APIRouter, Response, status

from nestd.accounts.github import GithubStatus
from nestd.api.deps import Context, RequireDevice
from nestd.claude_code.account import ClaudeAccountStatus

router = APIRouter(prefix="/api/accounts", dependencies=[RequireDevice])


@router.get("/github")
async def github_status(ctx: Context) -> GithubStatus:
    """From `gh`, checked again when the last check is an hour old."""
    return await ctx.github.status()


@router.post("/github/check")
async def check_github(ctx: Context) -> GithubStatus:
    return await ctx.github.check()


@router.get("/claude")
async def claude_status(ctx: Context) -> ClaudeAccountStatus:
    """From `claude auth status --json`; 502 when the CLI fails."""
    return await ctx.claude_account.status()


@router.post("/claude/login", status_code=status.HTTP_202_ACCEPTED)
async def claude_login(ctx: Context) -> Response:
    """Start `claude auth login --claudeai`, which opens the browser on the Mac; 409 while
    one runs. The outcome comes as `account.claude`.
    """
    await ctx.claude_account.login()
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/claude/logout")
async def claude_logout(ctx: Context) -> ClaudeAccountStatus:
    """Run `claude auth logout`; announced as `account.claude`."""
    return await ctx.claude_account.logout()
