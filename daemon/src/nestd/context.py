"""Everything the daemon shares between the API, CLI and modules."""

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta, tzinfo
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Self

import httpx
from claude_agent_sdk import ClaudeSDKClient

from nestd.accounts.codex import CodexAccount
from nestd.accounts.github import GithubAccount
from nestd.approvals.queue import ApprovalQueue
from nestd.approvals.store import ApprovalStore
from nestd.artifacts.ask import PageAsks
from nestd.artifacts.service import Artifacts
from nestd.artifacts.storage import PageStorage
from nestd.artifacts.store import ArtifactStore
from nestd.artifacts.tools import artifact_tools
from nestd.attachments.store import AttachmentStore
from nestd.auth.devices import DeviceService
from nestd.auth.secrets import SecretStore
from nestd.auth.token_socket import TokenSocket
from nestd.claude_code.account import ClaudeAccount
from nestd.claude_code.cli import ClaudeCli, ClaudeLocations
from nestd.claude_code.extensions import Extensions
from nestd.claude_sessions.archive import ChatArchive
from nestd.claude_sessions.catalog import ClaudeChats
from nestd.claude_sessions.live import LiveChats
from nestd.clock import Clock
from nestd.composer.service import ComposerActions
from nestd.config.errors import ConfigError
from nestd.config.loader import (
    load_settings,
    save_agent_defaults,
    save_configuration,
    save_pixie_defaults,
)
from nestd.config.models import AgentChoices, ArtifactSettings, ConfigurationSettings, Settings
from nestd.configuration.backups import Backups
from nestd.configuration.codex import CodexSetup
from nestd.configuration.engines import CodexLocations
from nestd.configuration.locations import Locations
from nestd.configuration.plugins import CodexPluginSetup
from nestd.configuration.project import ProjectSetup
from nestd.configuration.service import Configuration, prepare_engine
from nestd.configuration.watcher import ConfigurationWatcher
from nestd.configuration.wiring import build_sources
from nestd.connectors.registry import ConnectorRegistry
from nestd.engine.codex import STORE_PREFIX, CodexEngine
from nestd.engine.defaults import ChatDefaults
from nestd.engine.fetch import InfoClientFactory, fetch_details
from nestd.engine.service import EngineInfo
from nestd.engine.sign_ins import CLAUDE, CODEX, SignInStore
from nestd.engine.store import EngineInfoStore
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandRunner, run_command
from nestd.local_apps.apps import LocalApps
from nestd.modules.registry import Module, ModuleRegistry
from nestd.notifications.delivery import NotificationDelivery
from nestd.notifications.notifier import Notifier
from nestd.notifications.subscriptions import PushSubscriptionStore
from nestd.notifications.vapid import VapidKeys
from nestd.paths import AppPaths
from nestd.pixies.activity import ActivityStore
from nestd.pixies.agents import PixieAgents
from nestd.pixies.call_runs import PixieCallRuns
from nestd.pixies.call_store import CallStore
from nestd.pixies.calls import PixieCallLog
from nestd.pixies.files import PixieFiles
from nestd.pixies.habit_events import HabitEvents
from nestd.pixies.habit_store import HabitStore
from nestd.pixies.habit_tools import PixieHabitTools
from nestd.pixies.habits import HabitService
from nestd.pixies.nest_tools import PixieNest
from nestd.pixies.report_store import ReportStore
from nestd.pixies.reporting import Reports
from nestd.pixies.reports import REPORT_BACK, ReportBack
from nestd.pixies.runtime import PixieRuntime
from nestd.pixies.scheduler import HabitScheduler
from nestd.pixies.service import PixieService
from nestd.pixies.store import PixieStore
from nestd.pixies.team_store import TeamStore
from nestd.pixies.teams import TeamService
from nestd.pixies.triggers import HabitTriggers
from nestd.providers.base import AgentProvider
from nestd.providers.claude import ClaudeProvider
from nestd.providers.codex import CodexProvider
from nestd.providers.codex_engine import fetch_codex, fetch_codex_usage
from nestd.providers.codex_process import (
    CodexLaunch,
    TransportFactory,
    app_server_launch,
    bundled_binary,
    spawn,
)
from nestd.providers.codex_trust import forget_trust
from nestd.providers.shell_env import LoginShellEnv, ShellEnvSource, login_shell
from nestd.prs.monitor import PrMonitor
from nestd.prs.service import PullRequests
from nestd.reactions import SessionReactions, StateFollower
from nestd.repos.service import RepoService
from nestd.review.actions import ReviewActions
from nestd.review.publish import GitPublisher
from nestd.review.watch import ReviewWatcher
from nestd.search.index import SearchIndex
from nestd.sessions.commands import CommandStore
from nestd.sessions.engines import Engine
from nestd.sessions.manager import SessionManager
from nestd.sessions.queue import MessageQueue
from nestd.sessions.store import SessionStore
from nestd.storage.archiver import ChatArchiver
from nestd.storage.db import Database
from nestd.stuck.watcher import StuckWatcher
from nestd.tracking.service import Tracking
from nestd.usage.probe import ProbeClientFactory, UsageProbe
from nestd.usage.refresher import UsageRefresher
from nestd.usage.store import UsageStore
from nestd.usage.visibility import ClientVisibility
from nestd.usage.warnings import UsageWarnings
from nestd.worktrees.manager import WorktreeManager

# How long signing in to Claude or installing Claude Code may take (D104).
LONG_COMMAND_SECONDS = 900.0


logger = logging.getLogger(__name__)


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
    # Codex's models and login (B91).
    codex: CodexEngine
    # Which engine was signed in first, and the defaults Nest picks from it (B94).
    sign_ins: SignInStore
    chat_defaults: ChatDefaults
    pixies: PixieService
    pixie_calls: PixieCallLog
    teams: TeamService
    report_back: ReportBack
    habits: HabitService
    habit_scheduler: HabitScheduler
    habit_triggers: HabitTriggers
    reports: Reports
    composer: ComposerActions
    archiver: ChatArchiver
    usage_warnings: UsageWarnings
    github: GithubAccount
    claude_code: ClaudeCli
    claude_account: ClaudeAccount
    codex_account: CodexAccount
    extensions: Extensions
    artifacts: Artifacts
    # Settings > Configuration (B97).
    configuration: Configuration
    project_setup: ProjectSetup
    codex_plugins: CodexPluginSetup
    configuration_watcher: ConfigurationWatcher
    # None when the paths name no socket, as in tests.
    token_socket: TokenSocket | None

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
        shell_env: ShellEnvSource | None = None,
        claude_runner: CommandRunner | None = None,
        claude_locations: ClaudeLocations | None = None,
        codex_transport: TransportFactory = spawn,
        codex_locations: CodexLocations | None = None,
    ) -> Self:
        """Create directories, load settings and open the database. Starts nothing.

        `runner` runs the git and gh commands of approved work and reads pull requests
        (tests fake gh with it),
        `opener` the macOS `open` commands that launch local apps. `zone` decides which
        day a turn's usage counts for and when quiet hours are; None is the system's time
        zone. `push_transport` replaces the network for web push and ntfy in tests, and
        `probe_factory` the Claude client of the usage probe and `engine_factory` the one
        that reads the model list and account. `shell_env` replaces the login shell's
        environment read for the agent and `!` commands. `claude_runner` runs the `claude`
        command line and Claude Code's installer (D104), and `claude_locations` says where
        a standalone Claude Code may be. `codex_transport` starts Codex's app-server
        (tests use an in-memory one), and `codex_locations` says where a standalone Codex
        may be.
        """
        paths.ensure()
        settings = load_settings(paths)
        db = await Database.open(paths.db_path)
        bus = EventBus(db, clock)
        pixie_store = PixieStore(db, clock)
        notifier = Notifier(bus, pixie_store.name)
        repos = RepoService(paths, bus)
        attachments = AttachmentStore(db, clock, paths.attachments_dir)
        approvals = ApprovalQueue(ApprovalStore(db, clock), bus, notifier)
        tracking = Tracking(bus)
        usage = UsageStore(db, clock, zone)

        artifacts = Artifacts(
            ArtifactStore(db, clock, paths.artifacts_dir),
            bus,
            PageStorage(db, clock),
            PageAsks(
                db=db,
                bus=bus,
                clock=clock,
                usage=usage,
                factory=probe_factory,
                cwd=paths.ask_dir,
                settings=lambda: context.artifact_settings(),
                zone=zone,
            ),
        )
        connectors = ConnectorRegistry(db, clock, bus)
        store = SessionStore(db, clock)
        live_chats = LiveChats(paths.claude_dir)
        search = SearchIndex(db)
        commands = CommandStore(db, clock)
        sign_ins = SignInStore(db, clock)
        where = _locations(paths)

        async def signed_in(engine: str) -> None:
            """Note the engine's first sign in; its standard files are made when missing."""
            await sign_ins.record(engine)
            if where is not None:
                try:
                    await asyncio.to_thread(
                        prepare_engine, where, "claude" if engine == CLAUDE else "codex"
                    )
                except OSError as error:
                    logger.warning("could not prepare %s's files: %s", engine, error)

        engine = EngineInfo(
            EngineInfoStore(db, clock),
            fetch=lambda: fetch_details(engine_factory),
            clock=clock,
            account_file=paths.claude_account_file,
            settings_file=None if paths.claude_dir is None else paths.claude_dir / "settings.json",
            on_signed_in=lambda: signed_in(CLAUDE),
        )
        codex_home = paths.codex_home
        codex = CodexEngine(
            EngineInfoStore(db, clock, STORE_PREFIX),
            fetch=lambda: fetch_codex(
                codex_transport, app_server_launch(bundled_binary(), os.environ, codex_home)
            ),
            clock=clock,
            fetch_usage=lambda: fetch_codex_usage(
                codex_transport, app_server_launch(bundled_binary(), os.environ, codex_home)
            ),
            on_signed_in=lambda: signed_in(CODEX),
        )
        pixie_files = PixieFiles(paths.pixies_dir)
        team_store = TeamStore(db, clock)
        activity = ActivityStore(db, clock)
        shell = login_shell(os.environ, os.getuid())
        shell_env = shell_env or LoginShellEnv(shell).get

        async def report(pixie_id: str, text: str) -> None:
            await pixies.send(pixie_id, text, [], sender=REPORT_BACK)

        report_back = ReportBack(
            store=store,
            pixies=pixie_store,
            approvals=approvals,
            deliver=report,
            busy=lambda session_id: sessions.busy(session_id),
        )
        pixie_calls = PixieCallLog(CallStore(db, clock), pixie_store, team_store, bus)
        # The habit scheduler and the pixie calls across engines join once they exist:
        # they need the sessions (B42, B91).
        followers: list[StateFollower] = [report_back, pixie_calls]
        pixie_agents = PixieAgents(
            pixie_store,
            pixie_files,
            team_store,
            # Only the default engine (Claude) runs pixies as its own subagents (B91).
            inline=lambda provider: sessions.engines.by_name(provider) is sessions.engines.default,
        )
        sessions = SessionManager(
            store=store,
            bus=bus,
            repos=repos,
            worktrees=WorktreeManager(
                paths,
                # Codex trusted each folder it worked in; a removed worktree's entry goes.
                on_removed=None
                if codex_home is None
                else lambda path: forget_trust(codex_home, path),
            ),
            attachments=attachments,
            provider=provider
            or ClaudeProvider(
                paths.agent_gh_dir,
                shell_env=shell_env,
                claude_dir=paths.claude_dir,
            ),
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
                followers=followers,
            ),
            # Read for each new session, so edits through the API apply at once.
            defaults=lambda: context.settings.agents,
            idle_close=timedelta(minutes=settings.agents.idle_close_minutes),
            clock=clock,
            live_chats=live_chats,
            queue=MessageQueue(db, clock, bus),
            models=engine.find,
            default_model=engine.default_model,
            extras=lambda session: pixie_runtime.extras(session),
            agents=pixie_agents.for_session,
            calls=pixie_calls,
            nest_tools=lambda session: artifact_tools(artifacts, session),
            call_tools=lambda session, agents: call_runs.tools(session, agents),
            engines=[
                Engine(
                    CodexProvider(
                        paths.agent_gh_dir,
                        codex_home=codex_home,
                        transport=codex_transport,
                        shell_env=shell_env,
                    ),
                    models=codex.find,
                    ready=codex.require_signed_in,
                    default=codex.default_model,
                )
            ],
        )
        call_runs: PixieCallRuns = PixieCallRuns(
            pixies=pixie_store,
            sessions=sessions,
            bus=bus,
            defaults=lambda: context.settings.agents,
        )
        followers.append(call_runs)
        pixie_nest = PixieNest(
            pixies=pixie_store,
            sessions=sessions,
            store=store,
            approvals=approvals,
            bus=bus,
            activity=activity,
            clock=clock,
            zone=zone,
        )
        teams = TeamService(team_store, pixie_store, bus)
        pixies = PixieService(
            pixie_store,
            pixie_files,
            teams,
            sessions,
            bus,
            clock,
            # Read for each new chat, so edits through the API apply at once.
            defaults=lambda: context.settings.agents,
            activity=activity,
        )
        habit_store = HabitStore(db, clock)
        habit_events = HabitEvents(habit_store, bus, clock, zone)
        scheduler = HabitScheduler(
            store=habit_store,
            events=habit_events,
            pixies=pixie_store,
            files=pixie_files,
            sessions=sessions,
            approvals=approvals,
            usage=usage,
            clock=clock,
            zone=zone,
            defaults=lambda: context.settings.agents,
            pixie_settings=lambda: context.settings.pixies,
        )
        followers.append(scheduler)
        habits = HabitService(
            store=habit_store,
            pixies=pixie_store,
            events=habit_events,
            scheduler=scheduler,
            sessions=sessions,
            clock=clock,
        )
        reports = Reports(
            store=ReportStore(db, clock),
            habits=habit_store,
            pixies=pixie_store,
            chats=pixies,
            bus=bus,
            notifier=notifier,
            # Read for each report, so edits through the API apply at once.
            push_level=lambda: context.settings.notifications.pixie_report_level,
        )
        habit_tools = PixieHabitTools(
            habits=habits, store=habit_store, reports=reports, activity=activity
        )
        # Typed here: the session manager's `extras` above names it, and inferring it would
        # loop through the context the artifact asks read their settings from.
        pixie_runtime: PixieRuntime = PixieRuntime(
            pixie_store,
            pixie_files,
            repos,
            bus,
            clock,
            lambda pixie_id, session: (
                pixie_nest.tools(pixie_id, session.id, habit_run=session.habit_run_id is not None)
                + habit_tools.tools(pixie_id, session)
            ),
            called_prompt=pixie_agents.called_prompt,
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
            publisher=GitPublisher(runner, store, bus, paths.data_dir),
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
        devices = DeviceService(db, clock, secrets)
        claude_code = ClaudeCli(
            locations=claude_locations or ClaudeLocations.default(Path.home(), os.environ),
            run=claude_runner or run_command,
            # Signing in waits on the user in the browser; installing downloads.
            run_long=claude_runner or partial(run_command, time_limit=LONG_COMMAND_SECONDS),
            cwd=paths.data_dir,
            bus=bus,
        )

        def codex_launch() -> CodexLaunch:
            return app_server_launch(bundled_binary(), os.environ, codex_home)

        codex_setup = CodexSetup(codex_transport, codex_launch)
        backups = Backups(paths.data_dir / "config-backups", clock)
        claude_account = ClaudeAccount(claude_code, bus, clock)
        extensions = Extensions(claude_code, bus, paths.claude_dir)
        configuration = Configuration(
            where,
            backups,
            codex_setup,
            build_sources(
                claude_account=claude_account,
                claude_cli=claude_code,
                codex=codex,
                codex_locations=codex_locations
                or CodexLocations.default(Path.home(), os.environ, bundled_binary().executable),
                run=runner,
                cwd=paths.data_dir,
                extensions=extensions,
                connectors=connectors,
                repos=repos,
                settings=lambda: context.settings.configuration,
                save_settings=lambda changed: context.save_configuration_settings(changed),
            ),
        )
        context = cls(
            paths=paths,
            settings=settings,
            db=db,
            bus=bus,
            devices=devices,
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
                codex=codex.usage,
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
            codex=codex,
            sign_ins=sign_ins,
            chat_defaults=ChatDefaults(lambda: sessions.engines, sign_ins),
            pixies=pixies,
            pixie_calls=pixie_calls,
            teams=teams,
            report_back=report_back,
            habits=habits,
            habit_scheduler=scheduler,
            habit_triggers=HabitTriggers(
                bus=bus, sessions=store, habits=habit_store, scheduler=scheduler
            ),
            reports=reports,
            composer=ComposerActions(
                sessions=store.get,
                engine_of=sessions.engines.of,
                project_folder=lambda name: repos.get(name).path,
                user_memory=None if paths.claude_dir is None else paths.claude_dir / "CLAUDE.md",
                shell_env=shell_env,
                shell=shell,
                base_env=os.environ,
            ),
            archiver=ChatArchiver(
                sessions=sessions,
                clock=clock,
                # Read at each check, so a new limit from the API applies at once.
                settings=lambda: context.settings.storage,
            ),
            usage_warnings=UsageWarnings(
                bus=bus,
                db=db,
                # Read at each report, so a new level from the API applies at once.
                settings=lambda: context.settings.usage,
                push=notifications.push,
            ),
            github=GithubAccount(runner, paths.data_dir, clock),
            claude_code=claude_code,
            claude_account=claude_account,
            codex_account=CodexAccount(
                codex,
                codex_transport,
                lambda: app_server_launch(bundled_binary(), os.environ, codex_home),
                bus,
            ),
            extensions=extensions,
            artifacts=artifacts,
            configuration=configuration,
            project_setup=ProjectSetup(backups),
            codex_plugins=CodexPluginSetup(codex_setup),
            configuration_watcher=ConfigurationWatcher(
                bus, where, lambda: {repo.name: repo.path for repo in repos.list_repos()}
            ),
            # Each request gets the current token: a revoked local device is given a new one.
            token_socket=None
            if paths.token_socket is None
            else TokenSocket(paths.token_socket, devices.ensure_local_device),
        )
        return context

    async def settle_defaults(self) -> AgentChoices:
        """The agent defaults with nothing left to the engines (B94): nulls stored before
        are replaced by the values Nest picks and saved once they can be resolved, as are
        `[pixies] model` and pixies without a model or thinking level of their own.
        """
        resolved = await self.chat_defaults.resolve(self.settings.agents)
        choices = resolved.choices
        agents = self.settings.agents
        stored = (agents.provider, agents.model, agents.effort, agents.permission_mode)
        concrete = (choices.provider, choices.model, choices.effort, choices.permission_mode)
        try:
            if resolved.complete and stored != concrete:
                saved = save_agent_defaults(self.paths, choices)
                self.settings = self.settings.model_copy(update={"agents": saved})
            if self.settings.pixies.model is None:
                await self._settle_pixie_model(choices)
        except ConfigError as error:
            logger.warning("could not store the concrete defaults: %s", error)
        await self.pixies.settle_all()
        return choices

    async def _settle_pixie_model(self, choices: AgentChoices) -> None:
        """New Claude pixies start on the agent defaults' model when that is Claude's,
        else on Claude's default model.
        """
        claude = self.sessions.engines.default
        model = choices.model if choices.provider == claude.name else None
        model = model or await claude.default_model()
        if model is not None:
            pixies = self.settings.pixies.model_copy(update={"model": model})
            saved = save_pixie_defaults(self.paths, pixies)
            self.settings = self.settings.model_copy(update={"pixies": saved})

    def save_configuration_settings(
        self, configuration: ConfigurationSettings
    ) -> ConfigurationSettings:
        """Nest's own part of Settings > Configuration, saved and in use at once."""
        saved = save_configuration(self.paths, configuration)
        self.settings = self.settings.model_copy(update={"configuration": saved})
        return saved

    def artifact_settings(self) -> ArtifactSettings:
        """Read at each ask, so a change to the settings applies at once."""
        return self.settings.artifacts

    def usage_interval(self) -> timedelta | None:
        """How often the usage probe may run; None when the refresh is off."""
        minutes = self.settings.usage.refresh_minutes
        return timedelta(minutes=minutes) if minutes else None

    async def close(self) -> None:
        await self.claude_account.stop()
        await self.codex_account.stop()
        await self.claude_code.stop()
        await self.modules.stop_all()
        await self.notifications.close()
        await self.db.close()


def _locations(paths: AppPaths) -> Locations | None:
    """The engines' folders; None when Nest was started without one (tests)."""
    if paths.claude_dir is None or paths.claude_account_file is None or paths.codex_home is None:
        return None
    return Locations(paths.claude_dir, paths.claude_account_file, paths.codex_home)
