"""Claude Code's own command line, for the account, plugins and installing it (D104).

Nest runs the user's standalone Claude Code when one is installed, else the copy the
Claude Agent SDK bundles, so settings match what Claude Code itself does. Commands are run
through an injectable runner; tests never reach the real CLI.
"""

import asyncio
import importlib
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Self

import claude_agent_sdk
from pydantic import BaseModel, JsonValue

from nestd.errors import ConflictError, NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError, CommandRunner

# Runs a command with variables set: an added account's commands carry its profile (B98).
ENV_PROGRAM = "/usr/bin/env"
# Anthropic's official installer; it puts Claude Code in ~/.local/bin.
INSTALL_COMMAND = ("/bin/bash", "-c", "curl -fsSL https://claude.ai/install.sh | bash")
NOT_FOUND_AFTER_INSTALL = "the installer finished but Claude Code was not found"


class ClaudeCliError(NestError):
    """A `claude` command failed; its message is the CLI's own."""

    status_code = 502


class InstallRunningError(ConflictError):
    pass


@dataclass(frozen=True)
class ClaudeLocations:
    # The PATH searched for `claude`; "" searches nothing.
    search_path: str
    # Where Anthropic's installers put a standalone Claude Code, checked after the PATH.
    candidates: tuple[Path, ...]
    # The Claude Agent SDK's own copy, which Nest's agents run.
    bundled: Path
    bundled_version: str

    @classmethod
    def default(cls, home: Path, env: Mapping[str, str]) -> Self:
        package = Path(claude_agent_sdk.__file__).parent
        version: object = importlib.import_module("claude_agent_sdk._cli_version").__cli_version__
        return cls(
            search_path=env.get("PATH", ""),
            candidates=(
                home / ".local" / "bin" / "claude",
                home / ".claude" / "local" / "claude",
                Path("/opt/homebrew/bin/claude"),
                Path("/usr/local/bin/claude"),
            ),
            bundled=package / "_bundled" / "claude",
            bundled_version=str(version),
        )

    def standalone(self) -> Path | None:
        """The first standalone `claude` program found, never the SDK's own copy."""
        found = shutil.which("claude", path=self.search_path) if self.search_path else None
        for path in (*([Path(found)] if found else []), *self.candidates):
            if path != self.bundled and path.is_file() and os.access(path, os.X_OK):
                return path
        return None


class ClaudeCodeStatus(BaseModel):
    installed: bool
    path: str | None
    version: str | None
    # The version of the SDK's bundled Claude Code, which Nest's agents use.
    bundled_version: str


class ClaudeCli:
    def __init__(
        self,
        *,
        locations: ClaudeLocations,
        run: CommandRunner,
        run_long: CommandRunner,
        cwd: Path,
        bus: EventBus,
        run_sign_in: CommandRunner | None = None,
    ) -> None:
        """`run_long` runs commands that wait on the user or the network for longer, such
        as installing; `run_sign_in` signing in, which a cancel stops (default: `run_long`).
        """
        self.locations = locations
        self._run = run
        self._run_long = run_long
        self._run_sign_in = run_sign_in or run_long
        self._cwd = cwd
        self._bus = bus
        self._install: asyncio.Task[None] | None = None

    def program(self) -> Path:
        """The standalone Claude Code when installed, else the bundled one."""
        return self.locations.standalone() or self.locations.bundled

    async def run(
        self, args: Sequence[str], *, env: Mapping[str, str] | None = None, long: bool = False
    ) -> str:
        """Run `claude <args>` with `env` set (B98); a failure becomes a ClaudeCliError with
        the CLI's message.
        """
        return await self._call(self._run_long if long else self._run, args, env)

    async def sign_in(self, args: Sequence[str], env: Mapping[str, str] | None = None) -> str:
        """Run a sign-in command, which waits on the user in the browser."""
        return await self._call(self._run_sign_in, args, env)

    async def _call(
        self, run: CommandRunner, args: Sequence[str], env: Mapping[str, str] | None
    ) -> str:
        variables = [f"{name}={value}" for name, value in sorted((env or {}).items())]
        argv = [*([ENV_PROGRAM, *variables] if variables else []), str(self.program()), *args]
        try:
            return await run(argv, self._cwd)
        except FileNotFoundError as error:
            raise ClaudeCliError(f"Claude Code could not be started: {error}") from error
        except CommandError as error:
            message = error.stderr.strip() or f"claude {' '.join(args)} failed"
            raise ClaudeCliError(message) from error

    async def status(self) -> ClaudeCodeStatus:
        path = self.locations.standalone()
        version = None
        if path is not None:
            try:
                output = await self._run([str(path), "--version"], self._cwd)
            except (CommandError, OSError):
                pass
            else:
                version = output.split()[0] if output.split() else None
        return ClaudeCodeStatus(
            installed=path is not None,
            path=None if path is None else str(path),
            version=version,
            bundled_version=self.locations.bundled_version,
        )

    async def install(self) -> None:
        """Start Anthropic's installer in the background; 409 when Claude Code is
        installed or an install runs. Progress comes as `claude_code.install` events, then
        the new status as `claude_code.updated`.
        """
        if self._install is not None or self.locations.standalone() is not None:
            msg = "Claude Code is already installed or being installed"
            raise InstallRunningError(msg)
        await self._progress("running", None)
        self._install = asyncio.create_task(self._installing())

    async def stop(self) -> None:
        task, self._install = self._install, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _installing(self) -> None:
        try:
            try:
                output = await self._run_long(list(INSTALL_COMMAND), self._cwd)
            except (CommandError, OSError) as error:
                stderr = error.stderr if isinstance(error, CommandError) else str(error)
                await self._progress("failed", stderr.strip() or "the installer failed")
            else:
                if self.locations.standalone() is None:
                    await self._progress("failed", NOT_FOUND_AFTER_INSTALL)
                else:
                    lines = output.strip().splitlines()
                    await self._progress("done", lines[-1] if lines else None)
            status = await self.status()
            await self._bus.publish(types.CLAUDE_CODE_UPDATED, status.model_dump(mode="json"))
        finally:
            self._install = None

    async def _progress(self, state: str, message: str | None) -> None:
        payload: dict[str, JsonValue] = {"state": state, "message": message}
        await self._bus.publish(types.CLAUDE_CODE_INSTALL, payload)
