"""Starting `codex app-server` from the bundled `openai-codex-cli-bin` binary (B91, D113).

The binary comes with the daemon's dependencies, pinned, like Claude Code with the Agent
SDK: no separate download. Codex reads its home (config, MCP servers, skills, AGENTS.md
and login) from `CODEX_HOME`, the user's `~/.codex` unless Nest is told otherwise.
"""

import asyncio
import logging
import os
from collections import deque
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from nestd.gitops.remotes import scrub_credentials
from nestd.logging_setup import ENGINE_STDERR_LOGGER
from nestd.providers.codex_rpc import Transport

CODEX_HOME_ENV = "CODEX_HOME"
# The longest line read; an item with a command's whole output or an image is one line.
MAX_LINE_BYTES = 64 * 1024 * 1024
STDERR_LINES = 20
STDERR_CHARS = 300
CLOSE_SECONDS = 5.0

stderr_logger = logging.getLogger(ENGINE_STDERR_LOGGER)


@dataclass(frozen=True)
class CodexLaunch:
    args: tuple[str, ...]
    env: Mapping[str, str]
    cwd: Path | None = None


type TransportFactory = Callable[[CodexLaunch], Awaitable[Transport]]


@dataclass(frozen=True)
class CodexBinary:
    """The bundled executable and the folder of helpers (`rg`) it expects on PATH."""

    executable: Path
    path_dir: Path | None = None


def bundled_binary() -> CodexBinary:
    import codex_cli_bin  # pyright: ignore[reportMissingTypeStubs]

    executable: Path = codex_cli_bin.bundled_codex_path()
    path_dir: Path | None = codex_cli_bin.bundled_path_dir()
    return CodexBinary(executable, path_dir)


def app_server_launch(
    binary: CodexBinary,
    base_env: Mapping[str, str],
    codex_home: Path | None,
    extra_env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> CodexLaunch:
    """`base_env` is the daemon's environment with the user's login shell's over it;
    `extra_env` wins over both (a guarded run's credential-free git, D013).
    """
    env = {**base_env, **(extra_env or {})}
    if binary.path_dir is not None:
        env["PATH"] = os.pathsep.join(p for p in (str(binary.path_dir), env.get("PATH")) if p)
    if codex_home is not None:
        env[CODEX_HOME_ENV] = str(codex_home)
    args = (str(binary.executable), "app-server", "--listen", "stdio://")
    return CodexLaunch(args, env, cwd)


class ProcessTransport:
    """The app-server as a child process; each stderr line goes to the daemon log."""

    def __init__(self, process: asyncio.subprocess.Process) -> None:
        self._process = process
        self._lines: deque[str] = deque(maxlen=STDERR_LINES)
        self._drain = asyncio.create_task(self._drain_stderr())

    async def write(self, line: bytes) -> None:
        stdin = self._process.stdin
        assert stdin is not None  # noqa: S101 (started with a pipe)
        stdin.write(line)
        await stdin.drain()

    async def readline(self) -> bytes:
        stdout = self._process.stdout
        assert stdout is not None  # noqa: S101 (started with a pipe)
        return await stdout.readline()

    async def close(self) -> None:
        stdin = self._process.stdin
        if stdin is not None and not stdin.is_closing():
            stdin.close()
        try:
            async with asyncio.timeout(CLOSE_SECONDS):
                await self._process.wait()
        except TimeoutError:
            with suppress(ProcessLookupError):
                self._process.kill()
            await self._process.wait()
        await asyncio.gather(self._drain, return_exceptions=True)

    def stderr(self) -> str:
        """The last whole lines that fit in STDERR_CHARS, or the end of the last line."""
        kept: list[str] = []
        for line in reversed(self._lines):
            if kept and sum(len(k) + 1 for k in kept) + len(line) > STDERR_CHARS:
                break
            kept.append(line)
        text = scrub_credentials("\n".join(reversed(kept)))
        return text if len(text) <= STDERR_CHARS else "..." + text[3 - STDERR_CHARS :]

    async def _drain_stderr(self) -> None:
        stderr = self._process.stderr
        assert stderr is not None  # noqa: S101 (started with a pipe)
        while line := await stderr.readline():
            text = line.decode(errors="replace").strip()
            if text:
                stderr_logger.debug("Codex: %s", scrub_credentials(text))
                self._lines.append(text)


async def spawn(launch: CodexLaunch) -> Transport:
    process = await asyncio.create_subprocess_exec(
        *launch.args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(launch.env),
        cwd=launch.cwd,
        limit=MAX_LINE_BYTES,
    )
    return ProcessTransport(process)
