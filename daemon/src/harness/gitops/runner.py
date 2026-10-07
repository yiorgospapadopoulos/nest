"""Async subprocess runner for git and other command line tools (such as gh)."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

# Runs argv in a directory and returns stdout, raising CommandError on a non-zero exit.
# Injectable so tests can replace tools such as gh.
type CommandRunner = Callable[[Sequence[str], Path], Awaitable[str]]


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


async def run_command(argv: Sequence[str], cwd: Path) -> str:
    """Run `argv` in `cwd` and return its stdout."""
    # Otherwise the subprocess fails with a bare OSError that callers do not expect.
    problem = await asyncio.to_thread(_cwd_problem, cwd)
    if problem is not None:
        raise CommandError(argv, None, f"the working directory {cwd} {problem}")
    running = asyncio.ensure_future(_run(argv, cwd))
    try:
        returncode, stdout, stderr = await asyncio.shield(running)
    except asyncio.CancelledError:
        # Commands are short; stopping one midway could leave a lock file behind.
        await running
        raise
    if returncode:
        raise CommandError(argv, returncode, stderr.decode(errors="replace"))
    return stdout.decode(errors="replace")


def _cwd_problem(cwd: Path) -> str | None:
    if cwd.is_dir():
        return None
    return "is not a directory" if cwd.exists() else "does not exist"


async def _run(argv: Sequence[str], cwd: Path) -> tuple[int | None, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    return process.returncode, stdout, stderr


async def run_git(args: Sequence[str], cwd: Path) -> str:
    """Run `git <args>` in `cwd` and return its stdout."""
    try:
        return await run_command(["git", *args], cwd)
    except CommandError as error:
        raise GitError(args, error.returncode, error.stderr) from None
