"""The Claude account, through Claude Code's own `claude auth` commands (D104).

Nest never reads, stores or returns a token: it reads `claude auth status --json` and
starts `claude auth login`, which opens the browser on the Mac.
"""

import asyncio
import json
from datetime import datetime

from pydantic import BaseModel, JsonValue, ValidationError

from nestd.claude_code.cli import ClaudeCli, ClaudeCliError
from nestd.clock import Clock
from nestd.errors import ConflictError
from nestd.events import types
from nestd.events.bus import EventBus
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


class ClaudeAccount:
    def __init__(self, cli: ClaudeCli, bus: EventBus, clock: Clock) -> None:
        self._cli = cli
        self._bus = bus
        self._clock = clock
        self._login: asyncio.Task[None] | None = None

    async def status(self) -> ClaudeAccountStatus:
        output = await self._cli.run(["auth", "status", "--json"])
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
        """Start `claude auth login --claudeai`; 409 while one runs. The outcome comes as
        `account.claude`.
        """
        if self._login is not None:
            msg = "a sign in is already in progress"
            raise SignInRunningError(msg)
        self._login = asyncio.create_task(self._signing_in())

    async def logout(self) -> ClaudeAccountStatus:
        await self._cli.run(["auth", "logout"])
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
                await self._cli.run(["auth", "login", "--claudeai"], long=True)
            except ClaudeCliError as failure:
                error = str(failure)
            try:
                status = await self.status()
            except ClaudeCliError as failure:
                error = error or str(failure)
                status = ClaudeAccountStatus(
                    signed_in=False,
                    email=None,
                    organization=None,
                    plan=None,
                    method=None,
                    checked_at=self._clock.now(),
                )
            await self._announce(status, error)
        finally:
            self._login = None

    async def _announce(self, status: ClaudeAccountStatus, error: str | None) -> None:
        payload: dict[str, JsonValue] = {**status.model_dump(mode="json"), "error": error}
        await self._bus.publish(types.ACCOUNT_CLAUDE, payload)
