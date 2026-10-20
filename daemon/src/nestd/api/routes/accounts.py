"""Accounts in Settings (D104): Claude through Claude Code's own `claude auth` commands,
Codex through its app-server's own sign-in (B94), GitHub through the user's `gh` login.
No token is ever read or returned."""

from fastapi import APIRouter, Response, status

from nestd.accounts.codex import CodexAccountStatus, CodexSignIn
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


@router.get("/codex")
async def codex_status(ctx: Context) -> CodexAccountStatus:
    """Codex asked now; `signed_in` null with `error` when it could not be asked."""
    return await ctx.codex_account.status()


@router.post("/codex/login")
async def codex_login(ctx: Context) -> CodexSignIn:
    """Start Codex's ChatGPT sign in; the client opens `auth_url` in the browser on this
    Mac. 409 while one runs, 502 when Codex cannot start it. The outcome comes as
    `account.codex`.
    """
    return await ctx.codex_account.login()


@router.post("/codex/login/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_codex_login(ctx: Context) -> Response:
    """Stop the sign in that runs, if any; announced as `account.codex` without an error."""
    await ctx.codex_account.cancel()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/codex/logout")
async def codex_logout(ctx: Context) -> CodexAccountStatus:
    """Codex's `account/logout`; announced as `account.codex`. 502 when it fails."""
    return await ctx.codex_account.logout()
