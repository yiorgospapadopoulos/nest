"""Open a session's conversation in Claude Code, or a project in an editor, the file
manager or a terminal, the platform's way (`openers`)."""

import asyncio
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from nestd.errors import ConflictError
from nestd.gitops.runner import CommandRunner
from nestd.local_apps.editors import Editor, EditorId, default_editor
from nestd.local_apps.errors import AppNotInstalledError
from nestd.local_apps.launchers import (
    write_launcher,
    write_limit_reset_launcher,
    write_sign_in_launcher,
)
from nestd.local_apps.openers import RepoApp, Which, opener_for
from nestd.platform import Platform
from nestd.providers.base import RunAccount
from nestd.sessions.models import Session
from nestd.sessions.rules import require_workspace

__all__ = ["LIVE_WARNING", "ClaudeCodeLaunch", "LocalApps", "OpenTarget", "RepoApp"]

# What a project opens in: an app, or "editor" for the default editor.
type OpenTarget = RepoApp | Literal["editor"]

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
        editor_folders: Sequence[Path] | None = None,
    ) -> None:
        """`editor_folders` replaces where editors are looked for (tests)."""
        self._launchers_dir = launchers_dir
        self._opener = opener_for(platform, run, launchers_dir, which, editor_folders)

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

    async def open_limit_reset(self, account: RunAccount) -> Path:
        """Open a terminal running Claude Code's `/limit-reset` on the Claude account
        (B161). Only Claude Code uses the reset, after asking in the terminal.
        """
        launcher = self._launchers_dir / f"limit-reset-{account.id}{self._opener.launcher_suffix}"
        cwd = self._launchers_dir / "limit-reset"
        await asyncio.to_thread(write_limit_reset_launcher, launcher, cwd, account.env)
        await self._opener.open_launcher(launcher)
        return launcher

    async def open_claude_sign_in(
        self, account_id: str, program: Path, env: Mapping[str, str], profile: Path | None
    ) -> None:
        """Open a terminal running Claude Code's own `claude auth login` on the account
        (B162): Claude Code opens the browser there and keeps the login. `profile` is an
        added account's folder, None for the first account.
        """
        launcher = self._launchers_dir / f"sign-in-{account_id}{self._opener.launcher_suffix}"
        await asyncio.to_thread(write_sign_in_launcher, launcher, program, env, profile)
        await self._opener.open_launcher(launcher)

    async def installed_editors(self) -> list[Editor]:
        return await asyncio.to_thread(self._opener.installed_editors)

    async def default_editor(self, chosen: EditorId | None) -> Editor | None:
        return default_editor(await self.installed_editors(), chosen)

    async def open_repo(self, path: Path, app: OpenTarget, chosen: EditorId | None) -> None:
        """Open the project; `chosen` is the default editor picked in Settings."""
        if app == "editor":
            editor = await self.default_editor(chosen)
            if editor is None:
                msg = "No code editor is installed on this computer"
                raise AppNotInstalledError(msg)
            app = editor.id
        await self._opener.open_repo(path, app)
