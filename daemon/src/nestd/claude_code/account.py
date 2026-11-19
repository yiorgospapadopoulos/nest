"""The Claude account, through Claude Code's own `claude auth` commands (D104).

Nest never reads, stores or returns a token: it reads `claude auth status --json`. Signing
in is Claude Code's own `claude auth login`, which Nest opens in a terminal for the user
to run (B162, D190): Nest never starts a login itself.
"""

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime

from pydantic import BaseModel, ValidationError

from nestd.claude_code.cli import ClaudeCli, ClaudeCliError
from nestd.clock import Clock
from nestd.errors import ConflictError
from nestd.providers.claude_engine import plan_label


class SignInRunningError(ConflictError):
    pass


class ClaudeAccountStatus(BaseModel):
    signed_in: bool
    email: str | None
    organization: str | None
    # The subscription, such as "pro" or "max".
    plan: str | None
    # How Claude Code signs in, such as "claude.ai".
    method: str | None
    checked_at: datetime


class _AuthStatus(BaseModel):
    """What `claude auth status --json` prints that Nest uses; the rest is ignored."""

    loggedIn: bool  # noqa: N815 (the CLI's name)
    email: str | None = None
    orgName: str | None = None  # noqa: N815
    subscriptionType: str | None = None  # noqa: N815
    authMethod: str | None = None  # noqa: N815


def _read(output: str) -> _AuthStatus | None:
    try:
        return _AuthStatus.model_validate(json.loads(output))
    except (ValueError, ValidationError):
        return None


# Hears each sign in's outcome and each sign out, with the error a sign in ended with.
type Announce = Callable[[ClaudeAccountStatus, str | None], Awaitable[None]]

# Opens a terminal running `claude auth login` on the account.
type OpenSignIn = Callable[[], Awaitable[None]]

# How often a sign in in the terminal is checked for, and how long it is waited for.
SIGN_IN_POLL_SECONDS = 2.0
SIGN_IN_WAIT_SECONDS = 15 * 60.0
NOT_FINISHED = "The sign in was not finished in the terminal."


class ClaudeAccount:
    """One Claude account (B98): the first one with Claude Code's own environment, an
    added one with `env` pointing Claude Code at its profile folder, on every command.
    """

    def __init__(
        self,
        cli: ClaudeCli,
        clock: Clock,
        announce: Announce,
        open_sign_in: OpenSignIn,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._cli = cli
        self._clock = clock
        self._announce = announce
        self._open_sign_in = open_sign_in
        self._env = dict(env or {})
        self._login: asyncio.Task[None] | None = None
        # While the terminal opens, before the wait starts: a second sign in is refused.
        self._opening = False

    @property
    def signing_in(self) -> bool:
        return self._opening or self._login is not None

    async def status(self) -> ClaudeAccountStatus:
        try:
            output = await self._cli.run(["auth", "status", "--json"], env=self._env)
        except ClaudeCliError as error:
            # Signed out, Claude Code prints the same status and exits with an error (B168).
            signed_out = _read(error.output)
            if signed_out is None or signed_out.loggedIn:
                raise
            raw = signed_out
        else:
            answered = _read(output)
            if answered is None:
                msg = "claude auth status gave unexpected output"
                raise ClaudeCliError(msg)
            raw = answered
        return ClaudeAccountStatus(
            signed_in=raw.loggedIn,
            email=raw.email,
            organization=raw.orgName,
            plan=plan_label(raw.subscriptionType) if raw.subscriptionType else None,
            method=raw.authMethod,
            checked_at=self._clock.now(),
        )

    async def login(self) -> None:
        """Open `claude auth login` in a terminal, then wait for Claude Code to say it is
        signed in; 409 while a sign in runs. A terminal that cannot open raises at once.
        The outcome is announced.
        """
        if self.signing_in:
            msg = "a sign in is already in progress"
            raise SignInRunningError(msg)
        self._opening = True
        try:
            await self._open_sign_in()
        finally:
            self._opening = False
        self._login = asyncio.create_task(self._waiting())

    async def cancel(self) -> None:
        """Stop the sign in that runs, if one does; announced without an error."""
        task = self._login
        if task is None:
            return
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await self._announce(await self._status_or_signed_out(), None)

    async def logout(self) -> ClaudeAccountStatus:
        await self._cli.run(["auth", "logout"], env=self._env)
        status = await self.status()
        await self._announce(status, None)
        return status

    async def stop(self) -> None:
        task, self._login = self._login, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _waiting(self) -> None:
        """Ask Claude Code until it says signed in, up to SIGN_IN_WAIT_SECONDS. A failing
        ask means not yet.
        """
        try:
            error: str | None = NOT_FINISHED
            status = self._signed_out()
            deadline = asyncio.get_running_loop().time() + SIGN_IN_WAIT_SECONDS
            while asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(SIGN_IN_POLL_SECONDS)
                try:
                    status = await self.status()
                except ClaudeCliError:
                    continue
                if status.signed_in:
                    error = None
                    break
        finally:
            self._login = None
        # Once it no longer runs: hearing the outcome may remove the account.
        await self._announce(status, error)

    async def _status_or_signed_out(self) -> ClaudeAccountStatus:
        try:
            return await self.status()
        except ClaudeCliError:
            return self._signed_out()

    def _signed_out(self) -> ClaudeAccountStatus:
        return ClaudeAccountStatus(
            signed_in=False,
            email=None,
            organization=None,
            plan=None,
            method=None,
            checked_at=self._clock.now(),
        )
