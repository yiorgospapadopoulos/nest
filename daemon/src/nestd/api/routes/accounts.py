"""Accounts in Settings (D104): Claude through Claude Code's own `claude auth` commands,
Codex through its app-server's own sign-in (B94), GitHub through the user's `gh` login.
Each engine can have several accounts, one active at a time (B98); the routes named after
an engine act on its active account, as before. No token is ever read or returned."""

from fastapi import APIRouter, Response, status

from nestd.accounts.codex import CodexAccountStatus, CodexSignIn
from nestd.accounts.github import GithubStatus
from nestd.accounts.models import (
    Account,
    AccountList,
    AccountName,
    AccountProvider,
    AccountSignIn,
    BankedResetUse,
    BankedResetUsed,
)
from nestd.accounts.profiles import CLAUDE, CODEX
from nestd.api.deps import Context, RequireDevice
from nestd.claude_code.account import ClaudeAccountStatus
from nestd.providers.base import BankedResets

router = APIRouter(prefix="/api/accounts", dependencies=[RequireDevice])


@router.get("")
async def list_accounts(ctx: Context) -> AccountList:
    """Claude's accounts, then Codex's, in the user's order; statuses older than a minute
    are asked again (B98).
    """
    return await ctx.accounts.list()


@router.post("/refresh")
async def refresh_accounts(ctx: Context) -> AccountList:
    """New usage windows for every signed-in account; 429 within 20 s of the last."""
    return await ctx.accounts.refresh()


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
    return await (await ctx.accounts.claude_active()).status()


@router.post("/claude/login", status_code=status.HTTP_202_ACCEPTED)
async def claude_login(ctx: Context) -> Response:
    """Start `claude auth login --claudeai`, which opens the browser on the Mac; 409 while
    one runs. The outcome comes as `account.claude`.
    """
    await ctx.accounts.login(ctx.accounts.active_id(CLAUDE))
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/claude/logout")
async def claude_logout(ctx: Context) -> ClaudeAccountStatus:
    """Run `claude auth logout`; announced as `account.claude`."""
    return await (await ctx.accounts.claude_active()).logout()


@router.get("/codex")
async def codex_status(ctx: Context) -> CodexAccountStatus:
    """Codex asked now; `signed_in` null with `error` when it could not be asked."""
    return await (await ctx.accounts.codex_active()).status()


@router.post("/codex/login")
async def codex_login(ctx: Context) -> CodexSignIn:
    """Start Codex's ChatGPT sign in; the client opens `auth_url` in the browser on this
    Mac. 409 while one runs, 502 when Codex cannot start it. The outcome comes as
    `account.codex`.
    """
    started = await ctx.accounts.login(ctx.accounts.active_id(CODEX))
    return CodexSignIn(auth_url=started.auth_url or "")


@router.post("/codex/login/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_codex_login(ctx: Context) -> Response:
    """Stop the sign in that runs, if any; announced as `account.codex` without an error."""
    await ctx.accounts.cancel(ctx.accounts.active_id(CODEX))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/codex/logout")
async def codex_logout(ctx: Context) -> CodexAccountStatus:
    """Codex's `account/logout`; announced as `account.codex`. 502 when it fails."""
    return await (await ctx.accounts.codex_active()).logout()


@router.post("/{provider}", status_code=status.HTTP_202_ACCEPTED)
async def add_account(provider: AccountProvider, ctx: Context) -> AccountSignIn:
    """Add an account after the engine's others and start signing in to it: Claude opens
    the browser on the Mac, Codex gives `auth_url` to open. 409 while another sign in of
    the engine runs. One whose first sign in fails or is cancelled is removed again.
    """
    return await ctx.accounts.add(provider)


@router.post("/{account_id}/login", status_code=status.HTTP_202_ACCEPTED)
async def login(account_id: str, ctx: Context) -> AccountSignIn:
    """Sign in to the account again; 409 while a sign in of its engine runs."""
    return await ctx.accounts.login(account_id)


@router.post("/{account_id}/login/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_login(account_id: str, ctx: Context) -> Response:
    await ctx.accounts.cancel(account_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{account_id}/logout")
async def logout(account_id: str, ctx: Context) -> Account:
    """Sign out of that account only."""
    return await ctx.accounts.logout(account_id)


@router.put("/{account_id}/name")
async def rename(account_id: str, body: AccountName, ctx: Context) -> Account:
    """1 to 40 characters, trimmed; null or empty clears it."""
    return await ctx.accounts.rename(account_id, body.name)


@router.put("/{account_id}/active")
async def make_active(account_id: str, ctx: Context) -> AccountList:
    """Turns of the engine's chats and pixies start on it from now; 409 unless signed in."""
    return await ctx.accounts.set_active(account_id)


@router.delete("/{account_id}")
async def remove(account_id: str, ctx: Context) -> AccountList:
    """Sign out of an added account and delete it; 409 for the engine's first account."""
    return await ctx.accounts.remove(account_id)


@router.get("/{account_id}/banked-resets")
async def banked_resets(account_id: str, ctx: Context) -> BankedResets:
    """A Codex account's banked resets with each credit, read on its own app-server; 409
    for a Claude account.
    """
    return await ctx.accounts.banked_resets(account_id)


@router.post("/{account_id}/banked-resets/use")
async def use_banked_reset(account_id: str, body: BankedResetUse, ctx: Context) -> BankedResetUsed:
    """Use one of a signed-in Codex account's banked resets (409 otherwise, 502 when Codex
    fails); its limits are read again and announced.
    """
    return await ctx.accounts.use_banked_reset(account_id, body.credit_id)
