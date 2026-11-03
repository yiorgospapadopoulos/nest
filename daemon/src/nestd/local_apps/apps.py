"""Open a session's conversation in Claude Code, or a project in VS Code, the file manager
or a terminal, the platform's way (`openers`)."""

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

from nestd.errors import ConflictError
from nestd.gitops.runner import CommandRunner
from nestd.local_apps.launchers import write_launcher
from nestd.local_apps.openers import RepoApp, Which, opener_for
from nestd.platform import Platform
from nestd.sessions.models import Session
from nestd.sessions.rules import require_workspace

__all__ = ["LIVE_WARNING", "ClaudeCodeLaunch", "LocalApps", "RepoApp"]

LIVE_WARNING = "This chat is also open in Nest. Avoid sending messages from both at once."


@dataclass(frozen=True)
class ClaudeCodeLaunch:
    launcher: Path
    warning: str | None


class LocalApps:
    def __init__(
        self,
        run: CommandRunner,
        launchers_dir: Path,
        platform: Platform,
        which: Which = shutil.which,
    ) -> None:
        self._launchers_dir = launchers_dir
        self._opener = opener_for(platform, run, launchers_dir, which)

    async def open_in_claude_code(self, session: Session, live: bool) -> ClaudeCodeLaunch:
        """Open a terminal running `claude --resume` in the session's folder.

        `live` says Nest runs the session too; that is allowed, with a warning.
        """
        if session.provider_session_id is None:
            msg = f"session {session.id!r} has no Claude Code conversation to resume yet"
            raise ConflictError(msg)
        cwd = require_workspace(session)
        launcher = self._launchers_dir / f"{session.id}{self._opener.launcher_suffix}"
        await asyncio.to_thread(write_launcher, launcher, cwd, session.provider_session_id)
        await self._opener.open_launcher(launcher)
        return ClaudeCodeLaunch(launcher, LIVE_WARNING if live else None)

    async def open_repo(self, path: Path, app: RepoApp) -> None:
        await self._opener.open_repo(path, app)
