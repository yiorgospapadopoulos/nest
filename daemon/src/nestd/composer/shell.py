"""Run a `!` command from the composer, as Claude Code's bash mode does (B59).

The command runs in the user's shell with the login shell's environment, in the chat's
folder, with its output and error streams merged as a terminal shows them. What it printed
goes to Claude with the user's next message, in the block Claude Code sends.
"""

import asyncio
import os
import signal
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pydantic import BaseModel

# Claude Code's defaults for its Bash tool: two minutes, 30,000 characters of output.
TIMEOUT_SECONDS = 120.0
MAX_OUTPUT_CHARS = 30_000
_CHUNK = 65_536


class ShellResult(BaseModel):
    command: str
    # None when the command was stopped for running too long.
    exit_code: int | None
    output: str
    truncated: bool
    timed_out: bool
    # The block the client puts before the text of the next message it sends.
    context: str


async def run_command(
    command: str,
    cwd: Path,
    env: Mapping[str, str],
    shell: str,
    seconds: float = TIMEOUT_SECONDS,
    max_output: int = MAX_OUTPUT_CHARS,
) -> ShellResult:
    process = await asyncio.create_subprocess_exec(
        shell,
        "-c",
        command,
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        # Its own process group, so a timeout stops what it started in the background too.
        start_new_session=True,
    )
    stdout = cast(asyncio.StreamReader, process.stdout)
    kept = bytearray()
    timed_out = False
    try:
        async with asyncio.timeout(seconds):
            # Read to the end even past the limit, so the command never blocks on a full pipe.
            while chunk := await stdout.read(_CHUNK):
                kept += chunk[: max(0, max_output * 4 + 4 - len(kept))]
            exit_code: int | None = await process.wait()
    except TimeoutError:
        timed_out = True
        exit_code = None
        os.killpg(process.pid, signal.SIGKILL)
        await process.wait()
    text = kept.decode(errors="replace")
    truncated = len(text) > max_output
    output = text[:max_output]
    return ShellResult(
        command=command,
        exit_code=exit_code,
        output=output,
        truncated=truncated,
        timed_out=timed_out,
        context=context_block(
            command, output, truncated=truncated, timed_out=seconds if timed_out else None
        ),
    )


def context_block(command: str, output: str, *, truncated: bool, timed_out: float | None) -> str:
    """The command and its output as Claude Code puts them in the conversation."""
    notes = [
        "[output truncated]" if truncated else "",
        f"[timed out after {timed_out:g} seconds]" if timed_out is not None else "",
    ]
    body = "\n".join(part for part in (output.rstrip("\n"), *notes) if part)
    return (
        f"<bash-input>{command}</bash-input>\n"
        f"<bash-stdout>{body}</bash-stdout><bash-stderr></bash-stderr>"
    )
