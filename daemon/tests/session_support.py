"""A SessionManager wired to real stores, real git and the fake provider."""

import asyncio
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.approvals.queue import ApprovalQueue
from nestd.approvals.store import ApprovalStore
from nestd.attachments.store import AttachmentStore
from nestd.claude_sessions.live import LiveChats
from nestd.config.models import AgentDefaults, WorktreeConfig
from nestd.events.bus import EventBus
from nestd.gitops import runner
from nestd.notifications.notifier import Notifier
from nestd.paths import AppPaths
from nestd.providers.base import ModelOption
from nestd.repos.service import RepoService
from nestd.sessions.engines import AccountSource, Engine
from nestd.sessions.extras import RunExtrasSource
from nestd.sessions.manager import SessionManager
from nestd.sessions.models import CreateSession, Session, SessionState
from nestd.sessions.queue import MessageQueue
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import ChatAgentsSource, PixieCalls
from nestd.storage.db import Database
from nestd.worktrees.manager import WorktreeManager
from tests.async_support import until
from tests.claude_support import ClaudeHome
from tests.fake_provider import FakeProvider
from tests.fakes import FakeClock
from tests.git_support import init_repo
from tests.recording_hooks import RecordingHooks

# Worktree by default, so most tests exercise the full worktree flow.
DEFAULTS = AgentDefaults(
    model="claude-sonnet-5",
    effort="medium",
    permission_mode="acceptEdits",
    default_mode="worktree",
)


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
        self.queue = MessageQueue(db, clock, self.bus)
        self.repo_path = init_repo(tmp_path / "repo")
        self.claude = ClaudeHome(tmp_path / "claude")
        # Process ids the fake system reports alive.
        self.alive: set[int] = set()
        self.defaults = DEFAULTS
        # The engine's model list; None while unknown, so effort is not checked.
        self.models: list[ModelOption] | None = None
        self.manager = self.build(timedelta(hours=1))

    def build(
        self,
        idle_close: timedelta,
        extras: RunExtrasSource | None = None,
        agents: ChatAgentsSource | None = None,
        calls: PixieCalls | None = None,
        engines: Sequence[Engine] = (),
        accounts: AccountSource | None = None,
    ) -> SessionManager:
        return SessionManager(
            store=self.store,
            bus=self.bus,
            repos=self.repos,
            worktrees=self.worktrees,
            attachments=self.attachments,
            provider=self.provider,
            approvals=self.approvals,
            hooks=self.hooks,
            defaults=lambda: self.defaults,
            idle_close=idle_close,
            clock=self.clock,
            live_chats=LiveChats(self.claude.root, alive=lambda pid: pid in self.alive),
            queue=self.queue,
            models=self.find_model,
            extras=extras,
            agents=agents,
            calls=calls,
            engines=engines,
            accounts=accounts,
        )

    async def find_model(self, model: str | None) -> ModelOption | None:
        value = model or "default"
        return next((m for m in self.models or [] if m.value == value), None)

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


def gate_worktree_add(
    monkeypatch: pytest.MonkeyPatch, fail: bool = False
) -> tuple[asyncio.Event, asyncio.Event]:
    """Hold `git worktree add` until the second event is set; the first marks it started.
    With `fail`, git then fails instead of adding the worktree.
    """
    started, release = asyncio.Event(), asyncio.Event()
    run = runner._run  # pyright: ignore[reportPrivateUsage]

    async def gated(
        argv: Sequence[str], cwd: Path, time_limit: float, *rest: int | None
    ) -> tuple[int | None, bytes, bytes]:
        # After the hardening options (I-009), wherever they end.
        if any(list(argv[i : i + 2]) == ["worktree", "add"] for i in range(1, len(argv))):
            started.set()
            await release.wait()
            if fail:
                return 128, b"", b"fatal: no space left"
        return await run(argv, cwd, time_limit, *rest)

    monkeypatch.setattr(runner, "_run", gated)
    return started, release
