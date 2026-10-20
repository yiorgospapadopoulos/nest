"""Builds a pixie chat's run: its prompt, tools, projects, skills and permissions (D072),
and the run of a pixie called as a session of its own (B91).
"""

from collections.abc import Awaitable, Callable
from pathlib import Path

from nestd.clock import Clock
from nestd.events.bus import EventBus
from nestd.pixies.files import PixieFiles
from nestd.pixies.models import Pixie
from nestd.pixies.prompt import habit_system_prompt, recent_conversation, system_prompt
from nestd.pixies.store import PixieStore
from nestd.pixies.tools import pixie_tools
from nestd.providers.base import AgentTool
from nestd.repos.service import RepoService
from nestd.sessions.extras import RunExtras
from nestd.sessions.models import Session

# A pixie's Nest tools (B41) and its report and habit tools (B42) for a run of its chat
# or of one of its habits: the pixie's id, then the run's session.
type NestToolsSource = Callable[[str, Session], tuple[AgentTool, ...]]
# The prompt a pixie gets when it is called: its subagent prompt (B91).
type CalledPrompt = Callable[[Pixie], Awaitable[str]]


class PixieRuntime:
    def __init__(
        self,
        store: PixieStore,
        files: PixieFiles,
        repos: RepoService,
        bus: EventBus,
        clock: Clock,
        nest_tools: NestToolsSource,
        called_prompt: CalledPrompt | None = None,
    ) -> None:
        """`called_prompt` builds a called pixie's prompt; without it none is called."""
        self._nest_tools = nest_tools
        self._called_prompt = called_prompt
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
        dirs: tuple[Path, ...] = ()
        if pixie.project_access != "none":
            # Every pixie works in every project (D109).
            dirs = tuple(repo.path for repo in self._repos.list_repos())
        # `edit` works like any chat; the others may write only in the workdir.
        write_root = None if pixie.project_access == "edit" else self._files.workdir(pid)
        if session.called_by is not None:
            return await self._called(pixie, dirs, write_root)
        soul = self._files.read(pid, "soul").text
        memory = self._files.read(pid, "memory").text
        if session.habit_run_id is not None:
            # A habit run starts from its habit's prompt, not from the chat (B42).
            prompt = habit_system_prompt(pixie, soul, memory, self._files.notes(pid))
        else:
            recent = await recent_conversation(self._bus, session.id)
            prompt = system_prompt(pixie, soul, memory, self._files.notes(pid), recent)
        return RunExtras(
            system_prompt=prompt,
            extra_dirs=dirs,
            tools=pixie_tools(pixie, self._files, self._repos, self._clock)
            + self._nest_tools(pid, session),
            write_root=write_root,
            skills=tuple(pixie.skills),
        )

    async def _called(
        self, pixie: Pixie, dirs: tuple[Path, ...], write_root: Path | None
    ) -> RunExtras:
        """A called pixie works as its subagent would: its call prompt, its memory read-only
        and none of its own tools; it calls pixies only as a leader, through the run's call
        tool.
        """
        if self._called_prompt is None:
            msg = f"pixie {pixie.id!r} cannot be called as a session here"
            raise ValueError(msg)
        return RunExtras(
            system_prompt=await self._called_prompt(pixie),
            extra_dirs=dirs,
            tools=(),
            write_root=write_root,
            skills=tuple(pixie.skills),
        )
