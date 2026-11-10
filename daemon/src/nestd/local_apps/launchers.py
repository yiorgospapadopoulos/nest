"""Launcher scripts a terminal runs: `.command` files on macOS, which Terminal runs when
opened, `.sh` files on Linux."""

import re
import shlex
from collections.abc import Mapping
from pathlib import Path

LAUNCHER_MODE = 0o700


def launcher_script(cwd: Path, resume_id: str) -> str:
    """A script that continues the conversation with Claude Code in the session's folder.

    Both values are quoted; nothing else from the session reaches the shell.
    """
    return (
        "#!/bin/sh\n"
        "# Written by Nest: continues a session's conversation in Claude Code.\n"
        f"cd {shlex.quote(str(cwd))} && exec claude --resume {shlex.quote(resume_id)}\n"
    )


# An environment variable's name, as a shell takes it.
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def limit_reset_script(cwd: Path, env: Mapping[str, str]) -> str:
    """A script that starts Claude Code on `/limit-reset` in `cwd` (B161), on the account
    `env` points at (an added account's profile folder; empty for the first).

    `cwd` is an empty folder of Nest's own: Claude Code asks once whether to trust the
    folder it starts in, and trusting this one gives it nothing to read. Claude Code then
    uses the reset itself; Nest sends nothing.
    """
    settings = ""
    for name, value in env.items():
        if _NAME.fullmatch(name) is None:
            msg = f"not an environment variable name: {name!r}"
            raise ValueError(msg)
        settings += f"{name}={shlex.quote(value)} "
    run = f"env {settings}claude" if settings else "claude"
    return (
        "#!/bin/sh\n"
        "# Written by Nest: opens Claude Code to use the account's limit reset.\n"
        f"cd {shlex.quote(str(cwd))} && exec {run} /limit-reset\n"
    )


def write_launcher(path: Path, cwd: Path, resume_id: str) -> None:
    _write(path, launcher_script(cwd, resume_id))


def write_limit_reset_launcher(path: Path, cwd: Path, env: Mapping[str, str]) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    _write(path, limit_reset_script(cwd, env))


def _write(path: Path, script: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    path.chmod(LAUNCHER_MODE)
