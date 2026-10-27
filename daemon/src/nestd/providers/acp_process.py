"""Starting an ACP engine as a child process that speaks on its stdin and stdout (B107).

The engine's launcher (`acp.AcpLauncher`) says what to start and with which environment;
the process runs in the chat's folder. What the engine writes to stderr goes
to the daemon log, with credentials scrubbed, and its last lines name a crash.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from nestd.gitops.remotes import scrub_credentials
from nestd.providers.codex_process import MAX_LINE_BYTES, ProcessTransport, stderr_logger
from nestd.providers.codex_rpc import Transport


@dataclass(frozen=True)
class AcpLaunch:
    # The executable first.
    args: tuple[str, ...]
    # The whole environment of the process.
    env: Mapping[str, str]


# Starts the engine in a folder; tests substitute an in-memory agent.
type AcpTransportFactory = Callable[[AcpLaunch, Path], Awaitable[Transport]]


class AcpProcessTransport(ProcessTransport):
    """The engine process; its stderr lines go to the daemon log under its name."""

    def __init__(self, process: asyncio.subprocess.Process, label: str) -> None:
        self._label = label
        super().__init__(process)

    async def _drain_stderr(self) -> None:
        stderr = self._process.stderr
        assert stderr is not None  # noqa: S101 (started with a pipe)
        while line := await stderr.readline():
            text = line.decode(errors="replace").strip()
            if text:
                stderr_logger.debug("%s: %s", self._label, scrub_credentials(text))
                self._lines.append(text)


async def spawn_acp(launch: AcpLaunch, cwd: Path) -> Transport:
    process = await asyncio.create_subprocess_exec(
        *launch.args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=dict(launch.env),
        cwd=cwd,
        limit=MAX_LINE_BYTES,
    )
    return AcpProcessTransport(process, Path(launch.args[0]).name)
