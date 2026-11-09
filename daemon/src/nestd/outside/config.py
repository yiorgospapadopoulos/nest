"""Adds Nest's MCP server to Claude Code's and Codex's own config, and takes it out, with
their own `mcp add` and `mcp remove` commands (B151, D180). Only the user's main config
is changed: Claude Code's user scope and Codex's home."""

import sys
from collections.abc import Callable
from pathlib import Path

from nestd.claude_code.cli import ENV_PROGRAM, ClaudeCli, ClaudeCliError
from nestd.errors import NestError
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.outside.models import MCP_NAME, ClientKind
from nestd.paths import is_packaged


class McpConfigError(NestError):
    """Claude Code or Codex could not change its config; the message is its own."""

    status_code = 502


# A checkout's `nest`: <repo>/daemon/.venv/bin/nest, next to <repo>/daemon/src/nestd.
CHECKOUT_PROGRAM = Path(__file__).resolve().parents[3] / ".venv" / "bin" / "nest"


def nest_program(home: Path | None = None) -> Path | None:
    """The `nest` command at a path that outlives updates: the one the installer puts on
    the PATH (a link that follows releases), else a checkout's, else the one beside the
    daemon's Python. The daemon's own Python may sit in an engine environment whose folder
    an update deletes (B121), so it comes last."""
    candidates = [
        (home or Path.home()) / ".local" / "bin" / "nest",
        *([] if is_packaged() else [CHECKOUT_PROGRAM]),
        Path(sys.executable).parent / "nest",
    ]
    return next((path for path in candidates if path.is_file()), None)


class McpConfig:
    def __init__(
        self,
        *,
        claude: ClaudeCli,
        codex_program: Callable[[], Path | None],
        codex_home: Path | None,
        run: CommandRunner,
        cwd: Path,
        program: Callable[[], Path | None] = nest_program,
    ) -> None:
        """`codex_home` None leaves Codex alone, as in tests."""
        self._claude = claude
        self._codex_program = codex_program
        self._codex_home = codex_home
        self._run = run
        self._cwd = cwd
        self._program = program

    def command(self, kind: ClientKind) -> list[str] | None:
        """What a client runs: `nest mcp --client <kind>`, or the `nest` command itself."""
        program = self._program()
        if program is None:
            return None
        return [str(program)] if kind == "shell" else [str(program), "mcp", "--client", kind]

    async def add(self, kind: ClientKind) -> None:
        """Adds Nest's server to the client's config, replacing one already there; other
        clients have no config Nest writes."""
        if kind not in ("claude_code", "codex"):
            return
        command = self.command(kind)
        if command is None:
            msg = "The nest command was not found next to Nest's daemon. Reinstall Nest."
            raise McpConfigError(msg)
        await self.remove(kind)
        if kind == "claude_code":
            await self._claude_mcp(["add", "--scope", "user", MCP_NAME, "--", *command])
        else:
            await self._codex_mcp(["add", MCP_NAME, "--", *command])

    async def remove(self, kind: ClientKind) -> None:
        """Takes Nest's server out; one that is not there is no error."""
        try:
            if kind == "claude_code":
                await self._claude_mcp(["remove", "--scope", "user", MCP_NAME])
            elif kind == "codex":
                await self._codex_mcp(["remove", MCP_NAME])
        except McpConfigError as error:
            if "not found" not in str(error).lower() and "no mcp server" not in str(error).lower():
                raise

    async def _claude_mcp(self, args: list[str]) -> None:
        try:
            await self._claude.run(["mcp", *args])
        except ClaudeCliError as error:
            raise McpConfigError(str(error)) from error

    async def _codex_mcp(self, args: list[str]) -> None:
        program = self._codex_program()
        if program is None or self._codex_home is None:
            raise McpConfigError("Codex was not found.")
        argv = [ENV_PROGRAM, f"CODEX_HOME={self._codex_home}", str(program), "mcp", *args]
        try:
            await self._run(argv, self._cwd)
        except FileNotFoundError as error:
            raise McpConfigError(f"Codex could not be started: {error}") from error
        except CommandError as error:
            raise McpConfigError(error.stderr.strip() or f"codex mcp {args[0]} failed") from error
