"""Launcher scripts a terminal runs: `.command` files on macOS, which Terminal runs when
opened, `.sh` files on Linux."""

import re
import shlex
from collections.abc import Mapping
from pathlib import Path

LAUNCHER_MODE = 0o700


def launcher_script(program: Path, cwd: Path, resume_id: str) -> str:
    """A script that continues the conversation with Claude Code in the session's folder.

    `program` is the Claude Code Nest runs, by its path: an install with only the copy
    that comes with Nest has no `claude` for a terminal to find. Every value is quoted;
    nothing else from the session reaches the shell.
    """
    claude = shlex.quote(str(program))
    return (
        "#!/bin/sh\n"
        "# Written by Nest: continues a session's conversation in Claude Code.\n"
        f"cd {shlex.quote(str(cwd))} && exec {claude} --resume {shlex.quote(resume_id)}\n"
    )


# An environment variable's name, as a shell takes it.
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def limit_reset_script(program: Path, cwd: Path, env: Mapping[str, str]) -> str:
    """A script that starts Claude Code (`program`, as `launcher_script` takes it) on
    `/limit-reset` in `cwd` (B161), on the account `env` points at (an added account's
    profile folder; empty for the first).

    `cwd` is an empty folder of Nest's own: Claude Code asks once whether to trust the
    folder it starts in, and trusting this one gives it nothing to read. Claude Code then
    uses the reset itself; Nest sends nothing.
    """
    claude = _with_env(env, shlex.quote(str(program)))
    return (
        "#!/bin/sh\n"
        "# Written by Nest: opens Claude Code to use the account's limit reset.\n"
        f"cd {shlex.quote(str(cwd))} && exec {claude} /limit-reset\n"
    )


# In an added account's folder while Nest has the account; the folder goes with it.
SIGN_IN_MARKER = ".nest-account"


def sign_in_script(program: Path, env: Mapping[str, str], marker: Path | None) -> str:
    """A script that runs Claude Code's own `claude auth login` on the account `env` points
    at (B162, D190): Claude Code opens its sign-in page and keeps what it gets. Nest only
    reads `claude auth status` afterwards, so it never offers or sees the login itself.

    With `marker`, an added account's: a login finished after Nest removed the account (its
    sign in cancelled or not finished in time) is signed out again, as Claude Code would
    otherwise keep it under a folder Nest no longer shows.
    """
    claude = _with_env(env, shlex.quote(str(program)))
    if marker is None:
        return (
            "#!/bin/sh\n"
            "# Written by Nest: signs in to Claude Code with its own login.\n"
            f"exec {claude} auth login\n"
        )
    return (
        "#!/bin/sh\n"
        "# Written by Nest: signs in to Claude Code with its own login, and signs out again\n"
        "# when Nest removed the account meanwhile.\n"
        f"{claude} auth login\n"
        f"[ -e {shlex.quote(str(marker))} ] || exec {claude} auth logout\n"
    )


def _with_env(env: Mapping[str, str], command: str) -> str:
    """`command` run with `env` set; each name checked, each value quoted."""
    settings = ""
    for name, value in env.items():
        if _NAME.fullmatch(name) is None:
            msg = f"not an environment variable name: {name!r}"
            raise ValueError(msg)
        settings += f"{name}={shlex.quote(value)} "
    return f"env {settings}{command}" if settings else command


def write_launcher(path: Path, program: Path, cwd: Path, resume_id: str) -> None:
    _write(path, launcher_script(program, cwd, resume_id))


def write_limit_reset_launcher(
    path: Path, program: Path, cwd: Path, env: Mapping[str, str]
) -> None:
    cwd.mkdir(parents=True, exist_ok=True)
    _write(path, limit_reset_script(program, cwd, env))


def write_sign_in_launcher(
    path: Path, program: Path, env: Mapping[str, str], profile: Path | None
) -> None:
    """With `profile`, an added account's folder, which gets the marker first."""
    marker = None if profile is None else profile / SIGN_IN_MARKER
    if marker is not None:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch()
    _write(path, sign_in_script(program, env, marker))


def _write(path: Path, script: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script, encoding="utf-8")
    path.chmod(LAUNCHER_MODE)
