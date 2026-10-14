"""Async subprocess runner for git and other command line tools (such as gh)."""

import asyncio
from collections.abc import Awaitable, Callable, Generator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import cast

# Runs argv in a directory and returns stdout, raising CommandError on a non-zero exit.
# Injectable so tests can replace tools such as gh.
type CommandRunner = Callable[[Sequence[str], Path], Awaitable[str]]

# How long a git or gh command may take, network ones included (push, pull requests, a
# worktree checkout fetching large files), before it is killed and fails (BUG-20).
TIMEOUT_SECONDS = 300.0

# Set by `keeping_tail`. A context variable rather than an argument, so an injected runner
# such as a test fake keeps the plain CommandRunner signature.
_tail: ContextVar[int | None] = ContextVar("output_tail", default=None)
_READ_SIZE = 64 * 1024


@contextmanager
def keeping_tail(max_bytes: int) -> Generator[None]:
    """Within the block, `run_command` keeps only the last `max_bytes` of each output
    stream, read as it streams, so a huge output never sits in memory whole (BUG-97).

    A line the cut starts in the middle of is dropped, so the tail starts at a line.
    """
    if max_bytes <= 0:
        msg = f"the tail must be positive, not {max_bytes}"
        raise ValueError(msg)
    token = _tail.set(max_bytes)
    try:
        yield
    finally:
        _tail.reset(token)


def output_tail() -> int | None:
    """The byte limit `keeping_tail` set for commands run now, if any."""
    return _tail.get()


class CommandError(Exception):
    """A command exited with a non-zero status, or never started (returncode None)."""

    def __init__(self, argv: Sequence[str], returncode: int | None, stderr: str) -> None:
        status = "" if returncode is None else f" ({returncode})"
        super().__init__(f"{' '.join(argv)} failed{status}: {stderr.strip()}")
        self.argv = tuple(argv)
        self.returncode = returncode
        self.stderr = stderr


class GitError(CommandError):
    """A git command exited with a non-zero status, or never started (returncode None)."""

    def __init__(self, args: Sequence[str], returncode: int | None, stderr: str) -> None:
        super().__init__(["git", *args], returncode, stderr)
        self.args_ = tuple(args)

    @property
    def not_a_repository(self) -> bool:
        """The directory is not inside any git work tree (a plain folder, D041)."""
        return "not a git repository" in self.stderr


async def run_command(argv: Sequence[str], cwd: Path, time_limit: float = TIMEOUT_SECONDS) -> str:
    """Run `argv` in `cwd` and return its stdout; after `time_limit` seconds it is killed."""
    # Otherwise the subprocess fails with a bare OSError that callers do not expect.
    problem = await asyncio.to_thread(_cwd_problem, cwd)
    if problem is not None:
        raise CommandError(argv, None, f"the working directory {cwd} {problem}")
    running = asyncio.ensure_future(_run(argv, cwd, time_limit, _tail.get()))
    try:
        returncode, stdout, stderr = await asyncio.shield(running)
    except asyncio.CancelledError:
        # Stopping one midway could leave a lock file behind; the timeout bounds the wait.
        await asyncio.gather(running, return_exceptions=True)
        raise
    if returncode:
        raise CommandError(argv, returncode, stderr.decode(errors="replace"))
    return stdout.decode(errors="replace")


def _cwd_problem(cwd: Path) -> str | None:
    if cwd.is_dir():
        return None
    return "is not a directory" if cwd.exists() else "does not exist"


async def _run(
    argv: Sequence[str], cwd: Path, time_limit: float, tail: int | None
) -> tuple[int | None, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        async with asyncio.timeout(time_limit):
            if tail is None:
                stdout, stderr = await process.communicate()
            else:
                # Both are pipes, as asked for above.
                out = cast(asyncio.StreamReader, process.stdout)
                err = cast(asyncio.StreamReader, process.stderr)
                stdout, stderr = await asyncio.gather(_read_tail(out, tail), _read_tail(err, tail))
                await process.wait()
    except TimeoutError:
        process.kill()
        await process.wait()
        raise CommandError(argv, None, f"timed out after {time_limit:g} seconds") from None
    return process.returncode, stdout, stderr


async def _read_tail(stream: asyncio.StreamReader, limit: int) -> bytes:
    kept = bytearray()
    # Whether the bytes dropped so far ended with a complete line.
    at_line_start = True
    while chunk := await stream.read(_READ_SIZE):
        kept += chunk
        excess = len(kept) - limit
        if excess > 0:
            at_line_start = kept[excess - 1] == ord("\n")
            del kept[:excess]
    if at_line_start:
        return bytes(kept)
    newline = kept.find(b"\n")
    return b"" if newline == -1 else bytes(kept[newline + 1 :])


async def run_git(args: Sequence[str], cwd: Path, time_limit: float = TIMEOUT_SECONDS) -> str:
    """Run `git <args>` in `cwd` and return its stdout."""
    try:
        return await run_command(["git", *args], cwd, time_limit)
    except CommandError as error:
        raise GitError(args, error.returncode, error.stderr) from None
