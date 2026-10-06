"""A SessionManager wired to real stores, real git and the fake provider."""

from datetime import timedelta
from pathlib import Path

from harness.approvals.queue import ApprovalQueue
from harness.approvals.store import ApprovalStore
from harness.attachments.store import AttachmentStore
from harness.config.models import AgentDefaults, WorktreeConfig
from harness.events.bus import EventBus
from harness.notifications.notifier import Notifier
from harness.paths import AppPaths
from harness.repos.service import RepoService
from harness.sessions.manager import SessionManager
from harness.sessions.models import CreateSession, Session, SessionState
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from harness.worktrees.manager import WorktreeManager
from tests.async_support import until
from tests.fake_provider import FakeProvider
from tests.fakes import FakeClock
from tests.git_support import init_repo
from tests.recording_hooks import RecordingHooks

DEFAULTS = AgentDefaults(model="claude-sonnet-5", effort="medium", permission_mode="acceptEdits")


class Env:
    def __init__(self, tmp_path: Path, db: Database, clock: FakeClock) -> None:
        self.paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
        self.paths.ensure()
        self.db = db
        self.clock = clock
        self.bus = EventBus(db, clock)
        self.repos = RepoService(self.paths)
        self.worktrees = WorktreeManager(self.paths)
        self.attachments = AttachmentStore(db, clock, self.paths.attachments_dir)
        self.store = SessionStore(db, clock)
        self.approvals = ApprovalQueue(ApprovalStore(db, clock), self.bus, Notifier(self.bus))
        self.hooks = RecordingHooks()
        self.provider = FakeProvider()
        self.repo_path = init_repo(tmp_path / "repo")
        self.manager = self.build(timedelta(hours=1))

    def build(self, idle_close: timedelta) -> SessionManager:
        return SessionManager(
            store=self.store,
            bus=self.bus,
            repos=self.repos,
            worktrees=self.worktrees,
            attachments=self.attachments,
            provider=self.provider,
            approvals=self.approvals,
            hooks=self.hooks,
            defaults=DEFAULTS,
            idle_close=idle_close,
            clock=self.clock,
        )

    async def register(self, worktree: WorktreeConfig | None = None) -> None:
        await self.repos.register(self.repo_path)
        if worktree is not None:
            self.repos.update_worktree_config("repo", worktree)

    async def create(self, prompt: str = "Fix the bug\nDetails here", **fields: object) -> Session:
        request = CreateSession.model_validate({"repo": "repo", "prompt": prompt, **fields})
        return await self.manager.create(request)

    async def reach(self, session_id: str, state: SessionState) -> Session:
        """Wait until the session's latest state event announces `state`."""

        async def reached() -> bool:
            states = await self.states(session_id)
            return bool(states) and states[-1] == state

        await until(reached)
        return await self.store.get(session_id)

    async def event_types(self, session_id: str) -> list[str]:
        return [event.type for event in await self.bus.session_events(session_id)]

    async def states(self, session_id: str) -> list[object]:
        return [
            event.payload["state"]
            for event in await self.bus.session_events(session_id)
            if event.type == "session.state"
        ]
