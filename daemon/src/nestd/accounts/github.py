"""The user's GitHub login, read with their own `gh` (D104). The token is never read."""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from nestd.clock import Clock
from nestd.gitops.runner import CommandError, CommandRunner

# A status older than this is checked again when asked for.
MAX_AGE = timedelta(hours=1)
# gh's exit status when it has no login.
_AUTH_REQUIRED = 4

type GithubState = Literal["signed_in", "signed_out", "unavailable"]


class GithubStatus(BaseModel):
    # `unavailable`: gh is not installed or GitHub could not be reached.
    state: GithubState
    login: str | None
    checked_at: datetime


class GithubAccount:
    def __init__(self, run: CommandRunner, cwd: Path, clock: Clock) -> None:
        self._run = run
        self._cwd = cwd
        self._clock = clock
        self._status: GithubStatus | None = None
        self._lock = asyncio.Lock()

    async def status(self) -> GithubStatus:
        """The last status, checked again when there is none or it is old."""
        status = self._status
        if status is None or self._clock.now() - status.checked_at >= MAX_AGE:
            return await self.check()
        return status

    async def check(self) -> GithubStatus:
        async with self._lock:
            state, login = await self._read()
            self._status = GithubStatus(state=state, login=login, checked_at=self._clock.now())
            return self._status

    async def _read(self) -> tuple[GithubState, str | None]:
        try:
            output = await self._run(["gh", "api", "user", "--jq", ".login"], self._cwd)
        except FileNotFoundError:
            return "unavailable", None
        except CommandError as error:
            if error.returncode == _AUTH_REQUIRED or "gh auth login" in error.stderr:
                return "signed_out", None
            return "unavailable", None
        login = output.strip()
        return ("signed_in", login) if login else ("signed_out", None)
