"""`.command` files: Terminal runs them when opened, which needs no Automation permission."""

import shlex
from pathlib import Path

LAUNCHER_MODE = 0o700


def launcher_script(cwd: Path, resume_id: str) -> str:
    """A script that continues the conversation with Claude Code in the session's folder.

    Both values are quoted; nothing else from the session reaches the shell.
    """
    return (
        "#!/bin/sh\n"
        "# Written by harness: continues a session's conversation in Claude Code.\n"
        f"cd {shlex.quote(str(cwd))} && exec claude --resume {shlex.quote(resume_id)}\n"
    )


def write_launcher(path: Path, cwd: Path, resume_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(launcher_script(cwd, resume_id), encoding="utf-8")
    path.chmod(LAUNCHER_MODE)
