"""The composer's `!` and `#` for a chat (B59), outside the turn engine.

A `!` command's output is not kept by the daemon: the client puts the returned `context`
before the text of the next message it sends, so Claude reads it with that message, as in
Claude Code. A `#` memory is written at once and read by the chat's next run: in a
pixie's own chat it is a fact of the pixie's memory, on every engine (B112); elsewhere a
line of the instructions file the chat's engine reads (`memory_files`, B145).
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from nestd.clock import Clock
from nestd.composer.memory import append_memory
from nestd.composer.memory_files import CLAUDE_MD, MemoryFile
from nestd.composer.shell import MAX_OUTPUT_CHARS, TIMEOUT_SECONDS, ShellResult, run_command
from nestd.errors import ConflictError
from nestd.pixies.files import PixieFiles
from nestd.providers.shell_env import ShellEnvSource
from nestd.sessions.engines import Engine
from nestd.sessions.errors import PixieChatError
from nestd.sessions.models import Session
from nestd.sessions.rules import require_workspace

type MemoryScope = Literal["project", "user"]
# Where a memory went: `pixie` is the pixie's own memory, whichever scope was asked for.
type WrittenScope = Literal["project", "user", "pixie"]


class NoUserMemoryError(ConflictError):
    pass


class MemoryWritten(BaseModel):
    path: Path
    scope: WrittenScope
    line: str


class ComposerActions:
    def __init__(
        self,
        *,
        sessions: Callable[[str], Awaitable[Session]],
        engine_of: Callable[[Session], Engine],
        project_folder: Callable[[str], Path],
        memory_files: Mapping[str, MemoryFile],
        pixie_files: PixieFiles,
        clock: Clock,
        shell_env: ShellEnvSource,
        shell: str,
        base_env: Mapping[str, str],
        timeout: float = TIMEOUT_SECONDS,
        max_output: int = MAX_OUTPUT_CHARS,
    ) -> None:
        """`engine_of` gives a session's engine; `project_folder` names a project's
        folder; `memory_files` says where each engine reads its instructions, by engine
        name; `pixie_files` holds each pixie's memory.
        """
        self._sessions = sessions
        self._engine_of = engine_of
        self._project_folder = project_folder
        self._memory_files = memory_files
        self._pixie_files = pixie_files
        self._clock = clock
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
        """In a pixie's own chat, on any engine, add `text` to the pixie's memory as its
        memory tool does, whatever `scope` says (B112). Elsewhere append it to the file the
        chat's engine reads (B145): the project's (in its folder, not a worktree) or the
        user's own; 409 `unsupported_feature` on an engine that reads none.
        """
        session = await self._sessions(session_id)
        if session.pixie_id is not None:
            return await self._remember_for_pixie(session.pixie_id, text)
        engine = self._engine_of(session)
        engine.require("memory")
        path = self._memory_path(session, scope, engine.name)
        async with self._memory_lock:
            written = await append_memory(path, text)
        return MemoryWritten(path=written, scope=scope, line=f"- {' '.join(text.split())}")

    async def _remember_for_pixie(self, pixie_id: str, text: str) -> MemoryWritten:
        files = self._pixie_files
        today = self._clock.now().date()
        async with self._memory_lock:
            saved = files.add_fact(pixie_id, text, today)
        return MemoryWritten(
            path=files.memory_path(pixie_id), scope="pixie", line=saved.text.splitlines()[-1]
        )

    def _memory_path(self, session: Session, scope: MemoryScope, engine: str) -> Path:
        # The default engine is Claude's.
        file = self._memory_files.get(engine) or self._memory_files.get("claude")
        if file is None:
            file = MemoryFile((CLAUDE_MD,))
        if scope == "project":
            return file.project(self._project_folder(session.repo))
        path = file.for_user()
        if path is None:
            msg = "This engine keeps your own rules in its settings, not in a file"
            raise NoUserMemoryError(msg)
        return path
