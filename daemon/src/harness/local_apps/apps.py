"""Open a session's conversation in Claude Code, or a project in VS Code, Finder or Terminal.

Everything goes through macOS `open`, run by an injectable command runner.
"""

import asyncio
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from harness.errors import ConflictError
from harness.gitops.runner import CommandError, CommandRunner
from harness.local_apps.errors import AppNotInstalledError, LocalAppError
from harness.local_apps.launchers import write_launcher
from harness.sessions.models import Session
from harness.sessions.rules import require_workspace

type RepoApp = Literal["vscode", "finder", "terminal"]

# The app's name, and the `open` options that pick it.
_APPS: dict[RepoApp, tuple[str, tuple[str, ...]]] = {
    "vscode": ("Visual Studio Code", ("-a", "Visual Studio Code")),
    "finder": ("Finder", ()),
    "terminal": ("Terminal", ("-a", "Terminal")),
}
# What `open -a` prints when the app is not installed.
_NOT_INSTALLED = "Unable to find application"
LIVE_WARNING = "This chat is also open in harness. Avoid sending messages from both at once."


@dataclass(frozen=True)
class ClaudeCodeLaunch:
    launcher: Path
    warning: str | None


class LocalApps:
    def __init__(self, run: CommandRunner, launchers_dir: Path) -> None:
        self._run = run
        self._launchers_dir = launchers_dir

    async def open_in_claude_code(self, session: Session, live: bool) -> ClaudeCodeLaunch:
        """Open Terminal running `claude --resume` in the session's folder.

        `live` says harness runs the session too; that is allowed, with a warning.
        """
        if session.provider_session_id is None:
            msg = f"session {session.id!r} has no Claude Code conversation to resume yet"
            raise ConflictError(msg)
        cwd = require_workspace(session)
        launcher = self._launchers_dir / f"{session.id}.command"
        await asyncio.to_thread(write_launcher, launcher, cwd, session.provider_session_id)
        await self._open("Terminal", [str(launcher)])
        return ClaudeCodeLaunch(launcher, LIVE_WARNING if live else None)

    async def open_repo(self, path: Path, app: RepoApp) -> None:
        name, options = _APPS[app]
        await self._open(name, [*options, str(path)])

    async def _open(self, app_name: str, args: Sequence[str]) -> None:
        try:
            await self._run(["open", *args], self._launchers_dir)
        except CommandError as error:
            if _NOT_INSTALLED in error.stderr:
                msg = f"{app_name} is not installed on this Mac"
                raise AppNotInstalledError(msg) from error
            msg = f"could not open {app_name}: {error.stderr.strip()}"
            raise LocalAppError(msg) from error
        except OSError as error:
            msg = f"could not open {app_name}: {error}"
            raise LocalAppError(msg) from error
