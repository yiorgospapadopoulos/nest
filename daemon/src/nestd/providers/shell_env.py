"""The user's login shell environment, for the agent, its MCP servers and hooks (B59).

The daemon runs under launchd with a fixed PATH, so tools set up in the shell profile
(nvm, pyenv, variables it exports) were missing outside the Bash tool, which loads the
profile itself. The environment is read once from a login and interactive shell, as a
terminal starts it; when that fails the agent keeps the daemon's environment.
"""

import asyncio
import logging
import pwd
import subprocess
from collections.abc import Awaitable, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 10.0
DEFAULT_SHELL = "/bin/zsh"
# Printed before the environment, so whatever the profile prints first is skipped.
MARKER = "__NEST_SHELL_ENV__"
# What belongs to the shell that was read, not to the user's setup; and what tells a
# process it runs inside Claude Code, which the SDK sets itself.
EXCLUDED = frozenset(
    {
        "PWD",
        "OLDPWD",
        "SHLVL",
        "_",
        "TERM",
        "TERM_PROGRAM",
        "TERM_PROGRAM_VERSION",
        "TERM_SESSION_ID",
        "ITERM_SESSION_ID",
        "CLAUDECODE",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDE_AGENT_SDK_VERSION",
    }
)

# Runs a command and returns what it printed; raises when it fails or takes longer than
# the seconds given.
type ShellRunner = Callable[[Sequence[str], float], Awaitable[bytes]]
type ShellEnvSource = Callable[[], Awaitable[Mapping[str, str]]]


async def run_shell(args: Sequence[str], seconds: float) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *args,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        # No terminal to take over: an interactive shell would otherwise try.
        start_new_session=True,
    )
    try:
        async with asyncio.timeout(seconds):
            stdout, _ = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        raise
    if process.returncode != 0:
        msg = f"exited with {process.returncode}"
        raise RuntimeError(msg)
    return stdout


def login_shell(env: Mapping[str, str], uid: int) -> str:
    """The user's shell: SHELL, else the account's (launchd may not set SHELL)."""
    if env.get("SHELL"):
        return env["SHELL"]
    try:
        return pwd.getpwuid(uid).pw_shell or DEFAULT_SHELL
    except KeyError:
        return DEFAULT_SHELL


async def no_shell_env() -> Mapping[str, str]:
    """Nothing added: the agent gets the daemon's environment."""
    return {}


class LoginShellEnv:
    """The login shell's environment, read on first use and kept for the daemon's life."""

    def __init__(
        self, shell: str, runner: ShellRunner = run_shell, timeout: float = TIMEOUT_SECONDS
    ) -> None:
        self._shell = shell
        self._runner = runner
        self._timeout = timeout
        self._lock = asyncio.Lock()
        self._env: dict[str, str] | None = None

    async def get(self) -> Mapping[str, str]:
        async with self._lock:
            if self._env is None:
                self._env = await self._read()
            return self._env

    async def _read(self) -> dict[str, str]:
        command = f"printf '%s\\0' {MARKER}; command env -0"
        try:
            output = await self._runner([self._shell, "-ilc", command], self._timeout)
        except Exception as error:
            logger.warning(
                "could not read the login shell environment of %s (%s: %s); the agent "
                "gets the daemon's",
                self._shell,
                type(error).__name__,
                error,
            )
            return {}
        _, marker, entries = output.decode(errors="replace").rpartition(f"{MARKER}\0")
        if not marker:
            logger.warning(
                "the login shell environment of %s could not be read from its output; the "
                "agent gets the daemon's",
                self._shell,
            )
            return {}
        env: dict[str, str] = {}
        for entry in entries.split("\0"):
            name, equals, value = entry.partition("=")
            if equals and name and name not in EXCLUDED:
                env[name] = value
        return env
