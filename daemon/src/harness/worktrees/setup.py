"""Symlink gitignored files into a worktree and run the repo's setup commands."""

import asyncio
import os
import signal
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class LinkResult:
    linked: list[str] = field(default_factory=list[str])
    # Sources that do not exist in the main checkout.
    missing: list[str] = field(default_factory=list[str])
    # Targets already present in the worktree (for example tracked files); left alone.
    existing: list[str] = field(default_factory=list[str])


@dataclass(frozen=True)
class SetupResult:
    ok: bool
    log_path: Path
    command: str | None = None
    exit_code: int | None = None
    timed_out: bool = False


def link_files(entries: list[str], source_root: Path, target_root: Path) -> LinkResult:
    result = LinkResult()
    for entry in entries:
        source = source_root / entry
        target = target_root / entry
        if not source.exists():
            result.missing.append(entry)
        elif target.exists() or target.is_symlink():
            result.existing.append(entry)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(source)
            result.linked.append(entry)
    return result


async def run_commands(
    commands: list[str], cwd: Path, log_path: Path, timeout_seconds: int
) -> SetupResult:
    """Run each command with /bin/sh in `cwd`, stopping at the first failure or timeout."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # The log file is the commands' stdout and stderr, so it needs a real file handle.
    with log_path.open("ab", buffering=0) as log:
        for command in commands:
            log.write(f"$ {command}\n".encode())
            process = await asyncio.create_subprocess_exec(
                "/bin/sh",
                "-c",
                command,
                cwd=cwd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=log,
                stderr=asyncio.subprocess.STDOUT,
                # A process group of its own, so a timeout kills the command's children too.
                start_new_session=True,
            )
            try:
                exit_code = await asyncio.wait_for(process.wait(), timeout_seconds)
            except TimeoutError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
                log.write(f"timed out after {timeout_seconds}s\n".encode())
                return SetupResult(ok=False, log_path=log_path, command=command, timed_out=True)
            except asyncio.CancelledError:
                os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
                raise
            log.write(f"exit code {exit_code}\n".encode())
            if exit_code != 0:
                return SetupResult(
                    ok=False, log_path=log_path, command=command, exit_code=exit_code
                )
    return SetupResult(ok=True, log_path=log_path)
