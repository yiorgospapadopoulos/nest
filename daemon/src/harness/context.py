"""Everything the daemon shares between the API, CLI and modules."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta, tzinfo
from types import MappingProxyType
from typing import Self

from harness.approvals.queue import ApprovalQueue
from harness.approvals.store import ApprovalStore
from harness.attachments.store import AttachmentStore
from harness.auth.devices import DeviceService
from harness.auth.secrets import SecretStore
from harness.clock import Clock
from harness.config.loader import load_settings
from harness.config.models import Settings
from harness.connectors.registry import ConnectorRegistry
from harness.events.bus import EventBus
from harness.gitops.runner import CommandRunner, run_command
from harness.local_apps.apps import LocalApps
from harness.modules.registry import Module, ModuleRegistry
from harness.notifications.notifier import Notifier
from harness.paths import AppPaths
from harness.providers.base import AgentProvider
from harness.providers.claude import ClaudeProvider
from harness.reactions import SessionReactions
from harness.repos.service import RepoService
from harness.review.actions import ReviewActions
from harness.review.publish import GitPublisher
from harness.review.watch import ReviewWatcher
from harness.sessions.manager import SessionManager
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from harness.tracking.service import Tracking
from harness.usage.store import UsageStore
from harness.worktrees.manager import WorktreeManager


@dataclass
class AppContext:
    paths: AppPaths
    settings: Settings
    db: Database
    bus: EventBus
    devices: DeviceService
    modules: "ModuleRegistry[AppContext]"
    clock: Clock
    repos: RepoService
    attachments: AttachmentStore
    sessions: SessionManager
    approvals: ApprovalQueue
    tracking: Tracking
    reviews: ReviewActions
    usage: UsageStore
    connectors: ConnectorRegistry
    local_apps: LocalApps

    @classmethod
    async def build(
        cls,
        paths: AppPaths,
        secrets: SecretStore,
        clock: Clock,
        module_factories: "Mapping[str, Callable[[], Module[AppContext]]]" = MappingProxyType({}),
        provider: AgentProvider | None = None,
        runner: CommandRunner = run_command,
        opener: CommandRunner = run_command,
        zone: tzinfo | None = None,
    ) -> Self:
        """Create directories, load settings and open the database. Starts nothing.

        `runner` runs the git and gh commands of approved work (tests fake gh with it),
        `opener` the macOS `open` commands that launch local apps. `zone` decides which
        day a turn's usage counts for; None is the system's time zone.
        """
        paths.ensure()
        settings = load_settings(paths)
        db = await Database.open(paths.db_path)
        bus = EventBus(db, clock)
        notifier = Notifier(bus)
        repos = RepoService(paths)
        attachments = AttachmentStore(db, clock, paths.attachments_dir)
        approvals = ApprovalQueue(ApprovalStore(db, clock), bus, notifier)
        tracking = Tracking(bus)
        usage = UsageStore(db, clock, zone)
        connectors = ConnectorRegistry(db, clock, bus)
        store = SessionStore(db, clock)
        sessions = SessionManager(
            store=store,
            bus=bus,
            repos=repos,
            worktrees=WorktreeManager(paths),
            attachments=attachments,
            provider=provider or ClaudeProvider(paths.agent_gh_dir),
            approvals=approvals,
            hooks=SessionReactions(
                tracking, ReviewWatcher(approvals, tracking), notifier, usage, connectors
            ),
            defaults=settings.agents,
            idle_close=timedelta(minutes=settings.agents.idle_close_minutes),
            clock=clock,
        )
        reviews = ReviewActions(
            sessions=sessions,
            repos=repos,
            approvals=approvals,
            tracking=tracking,
            publisher=GitPublisher(runner, store, bus),
        )
        return cls(
            paths=paths,
            settings=settings,
            db=db,
            bus=bus,
            devices=DeviceService(db, clock, secrets),
            modules=ModuleRegistry(module_factories),
            clock=clock,
            repos=repos,
            attachments=attachments,
            sessions=sessions,
            approvals=approvals,
            tracking=tracking,
            reviews=reviews,
            usage=usage,
            connectors=connectors,
            local_apps=LocalApps(opener, paths.launchers_dir),
        )

    async def close(self) -> None:
        await self.modules.stop_all()
        await self.db.close()
