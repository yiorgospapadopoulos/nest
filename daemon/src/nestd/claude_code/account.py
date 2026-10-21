"""The Claude account, through Claude Code's own `claude auth` commands (D104).

Nest never reads, stores or returns a token: it reads `claude auth status --json` and
starts `claude auth login`, which opens the browser on the Mac.
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


# Hears each sign in's outcome and each sign out, with the error a sign in ended with.
type Announce = Callable[[ClaudeAccountStatus, str | None], Awaitable[None]]


class ClaudeAccount:
    """One Claude account (B98): the first one with Claude Code's own environment, an
    added one with `env` pointing Claude Code at its profile folder, on every command.
    """

    def __init__(
        self,
        cli: ClaudeCli,
        clock: Clock,
        announce: Announce,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._cli = cli
        self._clock = clock
        self._announce = announce
        self._env = dict(env or {})
        self._login: asyncio.Task[None] | None = None

    @property
    def signing_in(self) -> bool:
        return self._login is not None

    async def status(self) -> ClaudeAccountStatus:
        output = await self._cli.run(["auth", "status", "--json"], env=self._env)
        try:
            raw = _AuthStatus.model_validate(json.loads(output))
        except (ValueError, ValidationError) as error:
            msg = "claude auth status gave unexpected output"
            raise ClaudeCliError(msg) from error
        return ClaudeAccountStatus(
            signed_in=raw.loggedIn,
            email=raw.email,
            organization=raw.orgName,
            plan=plan_label(raw.subscriptionType) if raw.subscriptionType else None,
            method=raw.authMethod,
            checked_at=self._clock.now(),
        )

    async def login(self) -> None:
        """Start `claude auth login --claudeai`; 409 while one runs. The outcome is
        announced.
        """
        if self._login is not None:
            msg = "a sign in is already in progress"
            raise SignInRunningError(msg)
        self._login = asyncio.create_task(self._signing_in())

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

    async def _signing_in(self) -> None:
        try:
            error: str | None = None
            try:
                await self._cli.sign_in(["auth", "login", "--claudeai"], self._env)
            except ClaudeCliError as failure:
                error = str(failure)
            try:
                status = await self.status()
            except ClaudeCliError as failure:
                error = error or str(failure)
                status = self._signed_out()
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
