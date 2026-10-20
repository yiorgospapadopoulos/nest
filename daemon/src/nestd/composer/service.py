"""The composer's `!` and `#` for a chat (B59), outside the turn engine.

A `!` command's output is not kept by the daemon: the client puts the returned `context`
before the text of the next message it sends, so Claude reads it with that message, as in
Claude Code. A `#` memory is written at once and read by the chat's next run.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from nestd.composer.memory import append_memory
from nestd.composer.shell import MAX_OUTPUT_CHARS, TIMEOUT_SECONDS, ShellResult, run_command
from nestd.errors import ConflictError
from nestd.providers.shell_env import ShellEnvSource
from nestd.sessions.engines import Engine
from nestd.sessions.errors import PixieChatError
from nestd.sessions.models import Session
from nestd.sessions.rules import require_workspace

type MemoryScope = Literal["project", "user"]
MEMORY_FILE = "CLAUDE.md"


class NoUserMemoryError(ConflictError):
    pass


class MemoryWritten(BaseModel):
    path: Path
    scope: MemoryScope
    line: str


class ComposerActions:
    def __init__(
        self,
        *,
        sessions: Callable[[str], Awaitable[Session]],
        engine_of: Callable[[Session], Engine],
        project_folder: Callable[[str], Path],
        user_memory: Path | None,
        shell_env: ShellEnvSource,
        shell: str,
        base_env: Mapping[str, str],
        timeout: float = TIMEOUT_SECONDS,
        max_output: int = MAX_OUTPUT_CHARS,
    ) -> None:
        """`engine_of` gives a session's engine; `project_folder` names a project's
        folder; `user_memory` is the user's CLAUDE.md in Claude Code's config folder, None
        when there is none.
        """
        self._sessions = sessions
        self._engine_of = engine_of
        self._project_folder = project_folder
        self._user_memory = user_memory
        self._shell_env = shell_env
        self._shell = shell
        self._base_env = base_env
        self._timeout = timeout
        self._max_output = max_output
        self._memory_lock = asyncio.Lock()

    async def run_shell(self, session_id: str, command: str) -> ShellResult:
        """Run `command` in the chat's folder. A pixie may not run commands in its chats
        or the chats it starts, as it may not use git there (D072, B58).
        """
        session = await self._sessions(session_id)
        if session.pixie_id is not None or session.started_by_pixie is not None:
            raise PixieChatError("A pixie's chat cannot run shell commands.")
        cwd = require_workspace(session)
        env = {**self._base_env, **await self._shell_env(), "PWD": str(cwd)}
        return await run_command(
            command, cwd, env, self._shell, seconds=self._timeout, max_output=self._max_output
        )

    async def remember(self, session_id: str, text: str, scope: MemoryScope) -> MemoryWritten:
        """Append `text` to the project's CLAUDE.md (in its folder, not a worktree) or to
        the user's. 409 `unsupported_feature` in a chat on an engine that does not read
        CLAUDE.md (Codex, B91).
        """
        session = await self._sessions(session_id)
        self._engine_of(session).require("memory")
        path = self._memory_path(session, scope)
        async with self._memory_lock:
            written = await append_memory(path, text)
        return MemoryWritten(path=written, scope=scope, line=f"- {' '.join(text.split())}")

    def _memory_path(self, session: Session, scope: MemoryScope) -> Path:
        if scope == "user":
            if self._user_memory is None:
                msg = "Claude Code's config folder is not known, so there is no user memory"
                raise NoUserMemoryError(msg)
            return self._user_memory
        if session.pixie_id is not None:
            raise PixieChatError("A pixie's chat has no project memory; use user memory.")
        return self._project_folder(session.repo) / MEMORY_FILE
