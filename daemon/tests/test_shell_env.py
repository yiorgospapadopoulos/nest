"""B59: the agent, its MCP servers and hooks get the user's login shell environment."""

import asyncio
import logging
import os
import pwd
from collections.abc import Sequence
from pathlib import Path

import pytest

from nestd.providers.base import PermissionDecision, SessionSpec
from nestd.providers.claude import ClaudeProvider
from nestd.providers.shell_env import (
    MARKER,
    TIMEOUT_SECONDS,
    LoginShellEnv,
    login_shell,
    no_shell_env,
    run_shell,
)
from tests.test_claude_provider import Opened, ScriptedHandler


def env_output(*entries: str, before: str = "") -> bytes:
    body = "".join(f"{entry}\0" for entry in entries)
    return f"{before}{MARKER}\0{body}".encode()


class ScriptedShell:
    def __init__(self, output: bytes | Exception) -> None:
        self.output = output
        self.calls: list[tuple[list[str], float]] = []

    async def __call__(self, args: Sequence[str], seconds: float) -> bytes:
        self.calls.append((list(args), seconds))
        await asyncio.sleep(0)
        if isinstance(self.output, Exception):
            raise self.output
        return self.output


async def test_the_login_shells_exports_are_read_once() -> None:
    shell = ScriptedShell(
        env_output(
            "PATH=/Users/me/.nvm/bin:/usr/bin",
            "PYENV_ROOT=/Users/me/.pyenv",
            "MULTI=a=b\nc",
            "PWD=/x",
            "OLDPWD=/y",
            "SHLVL=2",
            "_=/usr/bin/env",
            "TERM_SESSION_ID=t",
            "CLAUDECODE=1",
            "not an entry",
            before="Welcome to zsh\0motd ",
        )
    )
    source = LoginShellEnv("/bin/zsh", shell)

    first, second = await asyncio.gather(source.get(), source.get())

    assert (
        first
        == second
        == {
            "PATH": "/Users/me/.nvm/bin:/usr/bin",
            "PYENV_ROOT": "/Users/me/.pyenv",
            "MULTI": "a=b\nc",
        }
    )
    assert await source.get() == first
    [(args, timeout)] = shell.calls
    # Login and interactive, as a terminal starts it, so both profile files are read.
    assert args[:2] == ["/bin/zsh", "-ilc"]
    assert MARKER in args[2]
    assert "env -0" in args[2]
    assert timeout == TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "output",
    [OSError("no such shell"), TimeoutError(), RuntimeError("exit 1"), b"PATH=/bin\0"],
)
async def test_a_shell_that_cannot_be_read_leaves_the_daemons_environment(
    output: bytes | Exception, caplog: pytest.LogCaptureFixture
) -> None:
    shell = ScriptedShell(output)
    source = LoginShellEnv("/bin/zsh", shell)

    with caplog.at_level(logging.WARNING):
        assert await source.get() == {}
        assert await source.get() == {}

    assert len(shell.calls) == 1
    assert "login shell environment" in caplog.text


async def test_no_shell_env_adds_nothing() -> None:
    assert await no_shell_env() == {}


async def test_run_shell_returns_what_the_command_printed() -> None:
    assert await run_shell(["/bin/sh", "-c", "printf 'a\\0b'"], 5) == b"a\0b"


async def test_run_shell_fails_on_a_failing_command() -> None:
    with pytest.raises(RuntimeError, match="exited with 3"):
        await run_shell(["/bin/sh", "-c", "exit 3"], 5)


async def test_run_shell_stops_a_shell_that_takes_too_long() -> None:
    with pytest.raises(TimeoutError):
        await run_shell(["/bin/sh", "-c", "sleep 5"], 0.1)


def test_the_login_shell_is_the_users(monkeypatch: pytest.MonkeyPatch) -> None:
    assert login_shell({"SHELL": "/opt/homebrew/bin/fish"}, os.getuid()) == (
        "/opt/homebrew/bin/fish"
    )
    # Under launchd SHELL may be unset: the account's shell.
    assert login_shell({}, os.getuid()) == pwd.getpwuid(os.getuid()).pw_shell
    monkeypatch.setattr(pwd, "getpwuid", _no_shell)
    assert login_shell({}, os.getuid()) == "/bin/zsh"
    monkeypatch.setattr(pwd, "getpwuid", _missing)
    assert login_shell({}, os.getuid()) == "/bin/zsh"


def _no_shell(uid: int) -> pwd.struct_passwd:
    return pwd.struct_passwd(("me", "*", uid, 20, "Me", "/Users/me", ""))


def _missing(uid: int) -> pwd.struct_passwd:
    raise KeyError(uid)


async def test_the_runs_environment_starts_from_the_login_shell(tmp_path: Path) -> None:
    """Nest's own entries win: the Claude app's settings and a guarded run's git block."""
    opened = Opened(tmp_path)

    async def shell_env() -> dict[str, str]:
        return {
            "PATH": "/Users/me/.nvm/bin:/usr/bin",
            "GH_TOKEN": "secret",
            "MCP_CONNECTION_NONBLOCKING": "false",
        }

    opened.provider = ClaudeProvider(tmp_path / "agent-gh", opened.factory, shell_env)
    handler = ScriptedHandler(PermissionDecision("allow"))

    _, guarded = await opened.open(SessionSpec(tmp_path, "default"), handler)
    _, normal = await opened.open(SessionSpec(tmp_path, "default", guard_git=False), handler)

    assert guarded.options.env["PATH"] == "/Users/me/.nvm/bin:/usr/bin"
    assert guarded.options.env["GH_TOKEN"] == ""
    assert guarded.options.env["MCP_CONNECTION_NONBLOCKING"] == "true"
    assert normal.options.env == {
        "PATH": "/Users/me/.nvm/bin:/usr/bin",
        "GH_TOKEN": "secret",
        "MCP_CONNECTION_NONBLOCKING": "true",
        "MCP_SERVER_CONNECTION_BATCH_SIZE": "8",
        "DISABLE_MICROCOMPACT": "1",
    }
