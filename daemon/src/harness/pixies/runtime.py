"""Builds a pixie chat's run: its prompt, tools, projects, skills and permissions (D072)."""

from collections.abc import Callable
from pathlib import Path

from harness.clock import Clock
from harness.events.bus import EventBus
from harness.pixies.files import PixieFiles
from harness.pixies.prompt import habit_system_prompt, recent_conversation, system_prompt
from harness.pixies.store import PixieStore
from harness.pixies.tools import pixie_tools
from harness.providers.base import AgentTool
from harness.repos.service import RepoService
from harness.sessions.extras import RunExtras
from harness.sessions.models import Session

# A pixie's harness tools (B41) and its report and habit tools (B42) for a run of its chat
# or of one of its habits: the pixie's id, then the run's session.
type HarnessToolsSource = Callable[[str, Session], tuple[AgentTool, ...]]


class PixieRuntime:
    def __init__(
        self,
        store: PixieStore,
        files: PixieFiles,
        repos: RepoService,
        bus: EventBus,
        clock: Clock,
        harness_tools: HarnessToolsSource,
    ) -> None:
        self._harness_tools = harness_tools
        self._store = store
        self._files = files
        self._repos = repos
        self._bus = bus
        self._clock = clock

    async def extras(self, session: Session) -> RunExtras:
        if session.pixie_id is None:
            msg = f"session {session.id!r} is not a pixie chat"
            raise ValueError(msg)
        pixie = await self._store.get(session.pixie_id)
        pid = pixie.id
        soul = self._files.read(pid, "soul").text
        memory = self._files.read(pid, "memory").text
        if session.habit_run_id is not None:
            # A habit run starts from its habit's prompt, not from the chat (B42).
            prompt = habit_system_prompt(pixie, soul, memory, self._files.notes(pid))
        else:
            recent = await recent_conversation(self._bus, session.id)
            prompt = system_prompt(pixie, soul, memory, self._files.notes(pid), recent)
        dirs: tuple[Path, ...] = ()
        if pixie.project_access != "none":
            dirs = tuple(
                repo.path
                for repo in self._repos.list_repos()
                if pixie.projects is None or repo.name in pixie.projects
            )
        return RunExtras(
            system_prompt=prompt,
            extra_dirs=dirs,
            tools=pixie_tools(pixie, self._files, self._repos, self._clock)
            + self._harness_tools(pid, session),
            # `edit` works like any chat; the others may write only in the workdir.
            write_root=None if pixie.project_access == "edit" else self._files.workdir(pid),
            skills=tuple(pixie.skills),
            allowed_tools=tuple(pixie.allowed_tools),
            disallowed_tools=tuple(pixie.disallowed_tools),
        )
