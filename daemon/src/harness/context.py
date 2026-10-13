"""Everything the daemon shares between the API, CLI and modules."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta, tzinfo
from types import MappingProxyType
from typing import Self

import httpx
from claude_agent_sdk import ClaudeSDKClient

from harness.approvals.queue import ApprovalQueue
from harness.approvals.store import ApprovalStore
from harness.attachments.store import AttachmentStore
from harness.auth.devices import DeviceService
from harness.auth.secrets import SecretStore
from harness.claude_sessions.archive import ChatArchive
from harness.claude_sessions.catalog import ClaudeChats
from harness.claude_sessions.live import LiveChats
from harness.clock import Clock
from harness.config.loader import load_settings
from harness.config.models import Settings
from harness.connectors.registry import ConnectorRegistry
from harness.engine.fetch import InfoClientFactory, fetch_details
from harness.engine.service import EngineInfo
from harness.engine.store import EngineInfoStore
from harness.events.bus import EventBus
from harness.gitops.runner import CommandRunner, run_command
from harness.local_apps.apps import LocalApps
from harness.modules.registry import Module, ModuleRegistry
from harness.notifications.delivery import NotificationDelivery
from harness.notifications.notifier import Notifier
from harness.notifications.subscriptions import PushSubscriptionStore
from harness.notifications.vapid import VapidKeys
from harness.paths import AppPaths
from harness.providers.base import AgentProvider
from harness.providers.claude import ClaudeProvider
from harness.prs.monitor import PrMonitor
from harness.prs.service import PullRequests
from harness.reactions import SessionReactions
from harness.repos.service import RepoService
from harness.review.actions import ReviewActions
from harness.review.publish import GitPublisher
from harness.review.watch import ReviewWatcher
from harness.search.index import SearchIndex
from harness.sessions.commands import CommandStore
from harness.sessions.manager import SessionManager
from harness.sessions.queue import MessageQueue
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from harness.stuck.watcher import StuckWatcher
from harness.tracking.service import Tracking
from harness.usage.probe import ProbeClientFactory, UsageProbe
from harness.usage.refresher import UsageRefresher
from harness.usage.store import UsageStore
from harness.usage.visibility import ClientVisibility
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
    notifications: NotificationDelivery
    claude_chats: ClaudeChats
    usage_refresher: UsageRefresher
    commands: CommandStore
    prs: PullRequests
    search: SearchIndex
    stuck: StuckWatcher
    engine: EngineInfo

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
        push_transport: httpx.AsyncBaseTransport | None = None,
        probe_factory: ProbeClientFactory = ClaudeSDKClient,
        engine_factory: InfoClientFactory = ClaudeSDKClient,
    ) -> Self:
        """Create directories, load settings and open the database. Starts nothing.

        `runner` runs the git and gh commands of approved work and reads pull requests
        (tests fake gh with it),
        `opener` the macOS `open` commands that launch local apps. `zone` decides which
        day a turn's usage counts for and when quiet hours are; None is the system's time
        zone. `push_transport` replaces the network for web push and ntfy in tests, and
        `probe_factory` the Claude client of the usage probe and `engine_factory` the one
        that reads the model list and account.
        """
        paths.ensure()
        settings = load_settings(paths)
        db = await Database.open(paths.db_path)
        bus = EventBus(db, clock)
        notifier = Notifier(bus)
        repos = RepoService(paths, bus)
        attachments = AttachmentStore(db, clock, paths.attachments_dir)
        approvals = ApprovalQueue(ApprovalStore(db, clock), bus, notifier)
        tracking = Tracking(bus)
        usage = UsageStore(db, clock, zone)
        connectors = ConnectorRegistry(db, clock, bus)
        store = SessionStore(db, clock)
        live_chats = LiveChats(paths.claude_dir)
        search = SearchIndex(db)
        commands = CommandStore(db, clock)
        engine = EngineInfo(
            EngineInfoStore(db, clock),
            fetch=lambda: fetch_details(engine_factory),
            clock=clock,
            account_file=paths.claude_account_file,
            settings_file=None if paths.claude_dir is None else paths.claude_dir / "settings.json",
        )
        sessions = SessionManager(
            store=store,
            bus=bus,
            repos=repos,
            worktrees=WorktreeManager(paths),
            attachments=attachments,
            provider=provider or ClaudeProvider(paths.agent_gh_dir),
            approvals=approvals,
            hooks=SessionReactions(
                tracking,
                ReviewWatcher(approvals, tracking),
                notifier,
                usage,
                connectors,
                commands,
                engine,
                repos,
            ),
            # Read for each new session, so edits through the API apply at once.
            defaults=lambda: context.settings.agents,
            idle_close=timedelta(minutes=settings.agents.idle_close_minutes),
            clock=clock,
            live_chats=live_chats,
            queue=MessageQueue(db, clock, bus),
            models=engine.find,
        )
        monitor = PrMonitor(
            store=store,
            bus=bus,
            approvals=approvals,
            notifier=notifier,
            run=runner,
            clock=clock,
            cwd=paths.data_dir,
        )
        reviews = ReviewActions(
            sessions=sessions,
            repos=repos,
            approvals=approvals,
            tracking=tracking,
            publisher=GitPublisher(runner, store, bus),
            prs=monitor,
        )
        notifications = NotificationDelivery(
            bus,
            PushSubscriptionStore(db, clock),
            VapidKeys(secrets),
            clock,
            # Read at delivery time, so edits through the API apply at once.
            settings=lambda: context.settings.notifications,
            transport=push_transport,
            zone=zone,
        )
        context = cls(
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
            notifications=notifications,
            claude_chats=ClaudeChats(
                claude_dir=paths.claude_dir,
                repos=repos,
                store=store,
                archive=ChatArchive(db, clock),
                bus=bus,
                live=live_chats,
                on_refresh=search.sync_claude_chats,
            ),
            usage_refresher=UsageRefresher(
                store=usage,
                bus=bus,
                clock=clock,
                probe=UsageProbe(probe_factory, paths.probe_dir),
                visibility=ClientVisibility(clock),
                # Read at each check, so a new interval from the API applies at once.
                interval=lambda: context.usage_interval(),
            ),
            commands=commands,
            prs=PullRequests(
                sessions=sessions,
                store=store,
                approvals=approvals,
                monitor=monitor,
                bus=bus,
                run=runner,
                cwd=paths.data_dir,
            ),
            search=search,
            stuck=StuckWatcher(
                store=store,
                bus=bus,
                notifier=notifier,
                clock=clock,
                # Read at each check, so new thresholds from the API apply at once.
                settings=lambda: context.settings.stuck,
            ),
            engine=engine,
        )
        return context

    def usage_interval(self) -> timedelta | None:
        """How often the usage probe may run; None when the refresh is off."""
        minutes = self.settings.usage.refresh_minutes
        return timedelta(minutes=minutes) if minutes else None

    async def close(self) -> None:
        await self.modules.stop_all()
        await self.notifications.close()
        await self.db.close()
