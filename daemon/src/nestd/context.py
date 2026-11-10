"""Everything the daemon shares between the API, CLI and modules."""

import asyncio
import logging
import os
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta, tzinfo
from functools import partial
from pathlib import Path
from types import MappingProxyType
from typing import Self

import httpx
from claude_agent_sdk import ClaudeSDKClient

from nestd.accounts.active import ActiveAccounts
from nestd.accounts.github import GithubAccount
from nestd.accounts.profiles import CLAUDE as CLAUDE_ACCOUNTS
from nestd.accounts.profiles import CODEX as CODEX_ACCOUNTS
from nestd.accounts.profiles import FirstAccount, Profiles
from nestd.accounts.service import Accounts
from nestd.accounts.signed_in import SignedIn
from nestd.accounts.store import AccountStore
from nestd.approvals.queue import ApprovalQueue
from nestd.approvals.store import ApprovalStore
from nestd.artifacts.ask import PageAsks
from nestd.artifacts.service import Artifacts
from nestd.artifacts.storage import PageStorage
from nestd.artifacts.store import ArtifactStore
from nestd.artifacts.tools import artifact_tools
from nestd.attachments.store import AttachmentStore
from nestd.auth.devices import LOCAL_DEVICE_ACCOUNT, DeviceService
from nestd.auth.secrets import KeyringSecretStore, SecretStore
from nestd.auth.token_socket import TokenSocket
from nestd.autopilot.keep_awake import KeepAwake
from nestd.autopilot.usage import weekly_used
from nestd.claude_code.cli import ClaudeCli, ClaudeLocations
from nestd.claude_code.extensions import Extensions
from nestd.claude_sessions.archive import ChatArchive
from nestd.claude_sessions.catalog import ClaudeChats
from nestd.claude_sessions.live import LiveChats
from nestd.clock import Clock
from nestd.codex_chats.catalog import CodexChats
from nestd.composer.memory_files import memory_files
from nestd.composer.service import ComposerActions
from nestd.computer.backends.base import Backend
from nestd.computer.service import ComputerService
from nestd.computer.setup import computer_service
from nestd.computer.tools import computer_tools
from nestd.config.errors import ConfigError
from nestd.config.loader import (
    load_settings,
    save_agent_defaults,
    save_configuration,
    save_pixie_defaults,
)
from nestd.config.models import (
    AgentChoices,
    ArtifactSettings,
    ConfigurationSettings,
    Settings,
)
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
from nestd.doctor.machine import Machine, this_machine
from nestd.engine.acp import AcpEngineService, AcpSetup, build_acp_engines
from nestd.engine.acp_install import InstallState
from nestd.engine.codex import STORE_PREFIX, CodexEngine
from nestd.engine.defaults import ChatDefaults
from nestd.engine.fetch import InfoClientFactory, fetch_details
from nestd.engine.service import EngineInfo
from nestd.engine.sign_ins import CLAUDE, CODEX, SignInStore
from nestd.engine.store import EngineInfoStore
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.features.catalog import packaged_catalog
from nestd.features.service import Features
from nestd.features.store import FeatureStore
from nestd.gitops.runner import CommandRunner, run_command
from nestd.issues.service import IssueService
from nestd.local.models import is_local
from nestd.local.service import LocalModels, LocalSetup
from nestd.local.store import LocalStore
from nestd.local_apps.apps import LocalApps
from nestd.machine import machine_name
from nestd.modules.registry import Module, ModuleRegistry
from nestd.notifications.delivery import NotificationDelivery
from nestd.notifications.notifier import Notifier
from nestd.notifications.subscriptions import PushSubscriptionStore
from nestd.notifications.vapid import VapidKeys
from nestd.outside.config import McpConfig
from nestd.outside.service import OutsideService
from nestd.outside.socket import ClientSocket
from nestd.outside.store import ClientStore
from nestd.outside.tokens import ClientTokens
from nestd.paths import AppPaths
from nestd.perf.collectors.context import ContextClientFactory
from nestd.perf.collectors.load import InProcess
from nestd.perf.service import Perf
from nestd.perf.timing import RouteTimings
from nestd.perf.wiring import PerfSetup, build_perf
from nestd.pixies.activity import ActivityStore
from nestd.pixies.agents import PixieAgents, native_subagents
from nestd.pixies.call_runs import PixieCallRuns
from nestd.pixies.call_store import BridgedCallStore, CallStore
from nestd.pixies.calls import PixieCallLog
from nestd.pixies.files import PixieFiles
from nestd.pixies.habit_events import HabitEvents
from nestd.pixies.habit_store import HabitStore
from nestd.pixies.habit_tools import PixieHabitTools
from nestd.pixies.habits import HabitService
from nestd.pixies.models import DEFAULT_PROVIDER
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
from nestd.platform import Platform, current_platform
from nestd.providers.acp import AcpProvider
from nestd.providers.acp_engines import ACP_ENGINES, AcpEngine
from nestd.providers.base import AgentProvider, EngineDetails, UsageInfo
from nestd.providers.claude import ClaudeProvider
from nestd.providers.codex import CodexProvider
from nestd.providers.codex_engine import CodexDetails, fetch_codex, fetch_codex_usage
from nestd.providers.codex_process import (
    CodexLaunch,
    TransportFactory,
    app_server_launch,
    bundled_binary,
    spawn,
)
from nestd.providers.codex_trust import forget_trust
from nestd.providers.one_off import cheapest
from nestd.providers.shell_env import LoginShellEnv, ShellEnvSource, login_shell
from nestd.prs.adopt import PrAdopter
from nestd.prs.guide import ReviewGuides
from nestd.prs.monitor import PrMonitor
from nestd.prs.service import PullRequests
from nestd.prs.stacks import Stacks
from nestd.reactions import SessionReactions, StateFollower
from nestd.repos.branch_watch import BranchWatch
from nestd.repos.fetching import RepoFetcher
from nestd.repos.places import PlaceBook
from nestd.repos.service import GENERAL, RepoService
from nestd.review.actions import ReviewActions
from nestd.review.publish import GitPublisher
from nestd.review.recheck import ReviewRecheck
from nestd.review.scope import ReviewScope
from nestd.review.watch import ReviewWatcher
from nestd.runs.blocks import PortBlocks
from nestd.runs.listening import PortProbe
from nestd.runs.listening import port_probe as find_port_probe
from nestd.runs.manager import RunManager
from nestd.search.index import SearchIndex
from nestd.sessions.commands import CommandStore
from nestd.sessions.engines import Engine
from nestd.sessions.manager import SessionManager
from nestd.sessions.merged_worktrees import MergedWorktrees
from nestd.sessions.models import Session
from nestd.sessions.queue import MessageQueue
from nestd.sessions.store import SessionStore
from nestd.sessions.turns import PLAIN_FOLDER_PROMPT
from nestd.storage.archiver import ChatArchiver
from nestd.storage.db import Database
from nestd.stuck.watcher import StuckWatcher
from nestd.tracking.service import Tracking
from nestd.triggers.access import WriteAccess
from nestd.triggers.chats import TriggeredChats
from nestd.triggers.poller import GitHubPoller
from nestd.triggers.service import ChatTriggerService
from nestd.triggers.store import TriggerStore
from nestd.updates.service import UpdateService, UpdateSetup
from nestd.usage.probe import ProbeClientFactory, UsageProbe
from nestd.usage.refresher import UsageRefresher
from nestd.usage.store import UsageStore
from nestd.usage.visibility import ClientVisibility
from nestd.usage.warnings import UsageWarnings
from nestd.voice.service import VoiceService, VoiceSetup
from nestd.worktrees.manager import WorktreeManager
from nestd.worktrees.options import claude_worktrees_dir
from nestd.worktrees.ownership import WORKTREE_PREFIX

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
    # Where new chats start in each project (B131).
    places: PlaceBook
    # The branch map's reload (B131).
    fetcher: RepoFetcher
    attachments: AttachmentStore
    sessions: SessionManager
    approvals: ApprovalQueue
    tracking: Tracking
    reactions: SessionReactions
    reviews: ReviewActions
    usage: UsageStore
    connectors: ConnectorRegistry
    local_apps: LocalApps
    notifications: NotificationDelivery
    claude_chats: ClaudeChats
    # Announces worktrees and checked-out branches changing outside Nest too (B96).
    branch_watch: BranchWatch
    # Removes merged worktrees in projects that ask for it (B141).
    merged_worktrees: MergedWorktrees
    # Checks pending reviews again when a project's branches move (B160).
    review_recheck: ReviewRecheck
    usage_refresher: UsageRefresher
    commands: CommandStore
    prs: PullRequests
    stacks: Stacks
    guides: ReviewGuides
    pr_adopter: PrAdopter
    # Open GitHub issues for new chats (B101).
    issues: IssueService
    search: SearchIndex
    stuck: StuckWatcher
    engine: EngineInfo
    # Codex's models and login (B91).
    codex: CodexEngine
    # The ACP engines Nest runs, by name, in the catalogue's order (B107).
    acp: dict[str, AcpEngineService]
    # Which engine was signed in first, and the defaults Nest picks from it (B94).
    sign_ins: SignInStore
    chat_defaults: ChatDefaults
    pixies: PixieService
    pixie_calls: PixieCallLog
    # The pixies runs call with call_pixie (B112).
    pixie_call_runs: PixieCallRuns
    teams: TeamService
    report_back: ReportBack
    habits: HabitService
    habit_scheduler: HabitScheduler
    habit_triggers: HabitTriggers
    # GitHub events that start habits and project chats (B148).
    chat_triggers: ChatTriggerService
    github_triggers: GitHubPoller
    reports: Reports
    composer: ComposerActions
    archiver: ChatArchiver
    usage_warnings: UsageWarnings
    github: GithubAccount
    claude_code: ClaudeCli
    # Every engine's accounts, and which one each uses (B98).
    accounts: Accounts
    extensions: Extensions
    artifacts: Artifacts
    # Chats that see and use apps, simulators, emulators and the shared browser (B150).
    computer: ComputerService
    # Speech to text for the phone and the Linux app (B154).
    voice: VoiceService
    # Settings > Configuration (B97).
    configuration: Configuration
    project_setup: ProjectSetup
    codex_plugins: CodexPluginSetup
    configuration_watcher: ConfigurationWatcher
    # Settings > Features (B103).
    features: Features
    # None when the paths name no socket, as in tests.
    token_socket: TokenSocket | None
    # Terminal agents (B151): what outside clients may do, and the socket that hands them
    # tokens (None when the paths name no socket, as in tests).
    outside: OutsideService
    outside_socket: ClientSocket | None
    # The machine's name for people, for clients on other machines (B105).
    machine: str
    # Model servers on this Mac or the network (B106).
    local: LocalModels
    # Each folder's ports and dev server (B108).
    runs: RunManager
    # Settings > Performance (B115): its runs, the API's route times, and the client its
    # load section calls the API with once the app exists.
    perf: Perf
    perf_timings: RouteTimings
    perf_fetch: InProcess
    # The system the daemon runs on (B117).
    platform: Platform
    # Following the newest engines without breaking this install.
    updates: UpdateService
    # The port `nestd serve --port` gave, which wins over the settings' one.
    port_flag: int | None = None
    # The machine the doctor's checks ask; None is this one.
    checks_machine: Machine | None = None

    def serving_port(self) -> int:
        """The port the daemon serves on: local models' runs reach its proxy there."""
        return self.port_flag if self.port_flag is not None else self.settings.server.port

    def doctor_machine(self) -> Machine:
        if self.checks_machine is not None:
            return self.checks_machine
        store = KeyringSecretStore(self.platform.secret_store_help)

        def read_secret() -> None:
            store.get(LOCAL_DEVICE_ACCOUNT)

        return this_machine(
            self.paths, self.platform, Path.home(), os.environ, self.serving_port(), read_secret
        )

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
        machine: Callable[[], Awaitable[str]] = machine_name,
        local_setup: LocalSetup | None = None,
        port_probe: PortProbe | None = None,
        acp_setup: AcpSetup | None = None,
        perf_client: ContextClientFactory = ClaudeSDKClient,
        platform: Platform | None = None,
        update_setup: UpdateSetup | None = None,
        computer_backends: Sequence[Backend] | None = None,
        voice_setup: VoiceSetup | None = None,
    ) -> Self:
        """Create directories, load settings and open the database. Starts nothing.

        `runner` runs the git and gh commands of approved work and reads pull requests
        (tests fake gh with it),
        `opener` the commands that launch local apps (macOS `open`, or the apps' own
        commands on Linux). `zone` decides which
        day a turn's usage counts for and when quiet hours are; None is the system's time
        zone. `push_transport` replaces the network for web push and ntfy in tests, and
        `probe_factory` the Claude client of the usage probe and `engine_factory` the one
        that reads the model list and account. `shell_env` replaces the login shell's
        environment read for the agent and `!` commands. `claude_runner` runs the `claude`
        command line and Claude Code's installer (D104), and `claude_locations` says where
        a standalone Claude Code may be. `codex_transport` starts Codex's app-server
        (tests use an in-memory one), and `codex_locations` says where a standalone Codex
        may be. `machine` reads the machine's name, once. `local_setup` is what local
        models reach: the network and the apps' folders. `port_probe` reads the ports a dev
        server run listens on (lsof, or /proc on Linux without it); None is the platform's.
        `acp_setup` is what the ACP engines reach: npm, their
        processes, the environment they start from (B107). `perf_client` is the one-off
        Claude client of Settings > Performance's context run (B115). `platform` is the
        system the daemon runs on (B117); None is the current one. `update_setup` is what
        the engine updates reach: the registries, uv, npm and the new environment's check.
        `voice_setup` is what voice input reaches: pip, the model download, its worker (B154).
        """
        system = platform or current_platform()
        paths.ensure()
        settings = load_settings(paths)
        db = await Database.open(paths.db_path)
        bus = EventBus(db, clock)
        account_store = AccountStore(db, clock)
        for engine in ACP_ENGINES:
            await account_store.ensure_first(engine.id)
        profiles = Profiles(
            paths.data_dir / "profiles",
            FirstAccount(paths.claude_dir, paths.claude_account_file, paths.codex_home),
        )
        active = await ActiveAccounts.load(account_store, profiles)
        sign_ins = SignInStore(db, clock)
        # Local models stand in only when no subscription engine is signed in: an ACP engine
        # does not count (B107).
        logins = SignedIn(account_store, active, sign_ins)
        local = LocalModels(
            store=LocalStore(db),
            secrets=secrets,
            bus=bus,
            clock=clock,
            port=lambda: context.serving_port(),
            setup=local_setup or LocalSetup.default(Path.home(), os.environ, system),
            zone=zone,
            signed_in=logins.any,
            claude_signed_in=logins.claude,
            has_chats=lambda: _has_chats(db),
        )
        await local.load()
        pixie_store = PixieStore(db, clock)
        notifier = Notifier(bus, pixie_store.name)
        places = PlaceBook(db)
        repos = RepoService(paths, bus, places)
        attachments = AttachmentStore(db, clock, paths.attachments_dir)
        approvals = ApprovalQueue(ApprovalStore(db, clock), bus, notifier)
        tracking = Tracking(bus)
        usage = UsageStore(db, clock, zone, active=active.id)

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
                account=lambda: active.prepare(CLAUDE_ACCOUNTS),
                local=local.ask_run,
            ),
        )
        connectors = ConnectorRegistry(db, clock, bus)
        store = SessionStore(db, clock)
        live_chats = LiveChats(paths.claude_dir)
        search = SearchIndex(db)
        codex_home = paths.codex_home

        def codex_launch(env: Mapping[str, str]) -> CodexLaunch:
            """An app-server on an account's Codex home: `env` names an added one's."""
            return app_server_launch(bundled_binary(), os.environ, codex_home, env)

        claude_chats = ClaudeChats(
            claude_dir=paths.claude_dir,
            repos=repos,
            store=store,
            archive=ChatArchive(db, clock),
            bus=bus,
            live=live_chats,
            on_refresh=search.sync_claude_chats,
            # The chats of the Codex home the user's own `codex` uses (B113).
            codex=CodexChats(
                codex_home=codex_home,
                transport=codex_transport,
                launch=lambda: codex_launch({}),
                clock=clock,
            ),
        )
        commands = CommandStore(db, clock)
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

        async def claude_details() -> EngineDetails:
            """On the active account (B98)."""
            account = await active.prepare(CLAUDE_ACCOUNTS)
            return await fetch_details(engine_factory, env=account.env)

        def claude_account_file() -> Path | None:
            """The active account's `.claude.json`: an added one keeps its own (B98)."""
            chosen = active.account(CLAUDE_ACCOUNTS)
            if chosen is None or chosen.profile is None:
                return paths.claude_account_file
            return chosen.profile / ".claude.json"

        async def claude_models_changed() -> None:
            await bus.publish_ephemeral(types.ENGINE_MODELS, {})

        engine = EngineInfo(
            EngineInfoStore(db, clock),
            fetch=claude_details,
            clock=clock,
            account_file=claude_account_file,
            settings_file=None if paths.claude_dir is None else paths.claude_dir / "settings.json",
            on_signed_in=lambda: signed_in(CLAUDE),
            on_models=claude_models_changed,
        )

        async def active_codex() -> CodexLaunch:
            return codex_launch((await active.prepare(CODEX_ACCOUNTS)).env)

        async def codex_details() -> CodexDetails:
            return await fetch_codex(codex_transport, await active_codex())

        async def codex_usage() -> UsageInfo | None:
            return await fetch_codex_usage(codex_transport, await active_codex())

        codex = CodexEngine(
            EngineInfoStore(db, clock, STORE_PREFIX),
            fetch=codex_details,
            clock=clock,
            fetch_usage=codex_usage,
            on_signed_in=lambda: signed_in(CODEX),
        )

        async def codex_small_model() -> str | None:
            return cheapest((await codex.models()).models)

        pixie_files = PixieFiles(paths.pixies_dir)
        team_store = TeamStore(db, clock)
        activity = ActivityStore(db, clock)
        shell = login_shell(os.environ, os.getuid())
        shell_env = shell_env or LoginShellEnv(shell).get
        acp_setup = acp_setup or AcpSetup()

        async def engine_state(engine: AcpEngine, state: InstallState) -> None:
            await bus.publish_ephemeral(
                types.ENGINE_STATE,
                {
                    "name": engine.id,
                    "state": state.state,
                    "version": state.version,
                    "state_detail": state.detail,
                },
            )

        acp = build_acp_engines(
            root=paths.engines_dir,
            db=db,
            clock=clock,
            secrets=secrets,
            shell_env=shell_env,
            active=active.prepare,
            on_change=engine_state,
            setup=acp_setup,
            environments=paths.environments_dir,
        )
        runs = RunManager(
            bus=bus,
            # Read at each use, so new port settings apply to the next block given.
            blocks=PortBlocks(db, clock, lambda: context.settings.ports),
            repos=repos,
            clock=clock,
            logs_dir=paths.logs_dir,
            probe=port_probe
            or find_port_probe(
                system,
                ":".join((os.environ.get("PATH", ""), system.service_path(Path.home()))),
            ),
            shell_env=shell_env,
            base_env=os.environ,
        )

        async def report(pixie_id: str, text: str) -> None:
            await pixies.send(pixie_id, text, [], sender=REPORT_BACK)

        report_back = ReportBack(
            store=store,
            pixies=pixie_store,
            approvals=approvals,
            deliver=report,
            busy=lambda session_id: sessions.busy(session_id),
        )
        bridged_calls = BridgedCallStore(db, clock)
        pixie_calls = PixieCallLog(
            CallStore(db, clock),
            pixie_store,
            team_store,
            bus,
            bridged=bridged_calls,
            engine_of=lambda session_id: _engine_of(store, session_id),
        )
        # The habit scheduler and the pixie calls across engines join once they exist:
        # they need the sessions (B42, B91).
        followers: list[StateFollower] = [report_back, pixie_calls]

        def can_push() -> bool:
            return context.settings.limits.can_push

        # Claude and Codex run the pixies on their own engine as their own subagents (B112).
        # The default engine stands for Claude (a fake one in tests), so its pixies stay
        # its own subagents, as do Codex's on Codex (B112).
        pixie_agents = PixieAgents(
            pixie_store,
            pixie_files,
            team_store,
            inline=lambda provider: (
                DEFAULT_PROVIDER
                if sessions.engines.by_name(provider) is sessions.engines.default
                else native_subagents(provider)
            ),
            can_push=can_push,
            computer=lambda: context.settings.computer_use.pixies,
        )
        computer = computer_service(
            data_dir=paths.data_dir,
            env=os.environ,
            settings=lambda: context.settings.computer_use,
            store=store,
            bus=bus,
            ask=lambda session_id, payload, notice: sessions.choose(session_id, payload, notice),
            interrupt=lambda session_id: sessions.interrupt(session_id),
            backends=computer_backends,
        )
        followers.append(computer)
        issues = IssueService(
            repo=repos.get, run=runner, clock=clock, cwd=paths.data_dir, chats=store.issue_chats
        )
        review_scope = ReviewScope(store.changed_paths)
        reactions = SessionReactions(
            tracking,
            ReviewWatcher(approvals, tracking, review_scope),
            notifier,
            usage,
            connectors,
            commands,
            engine,
            repos,
            store.get,
            followers=followers,
        )
        worktrees = WorktreeManager(
            paths,
            # Codex trusted each folder it worked in; a removed worktree's entry goes.
            on_removed=None if codex_home is None else lambda path: forget_trust(codex_home, path),
            bus=bus,
            runs=runs,
            defaults=lambda: context.settings.worktrees,
        )

        async def subagents_working(session_id: str) -> bool:
            return (await tracking.sync(session_id)).agents.subagents_working()

        sessions = SessionManager(
            subagents_working=subagents_working,
            store=store,
            bus=bus,
            repos=repos,
            worktrees=worktrees,
            attachments=attachments,
            provider=provider
            or ClaudeProvider(
                shell_env=shell_env,
                claude_dir=paths.claude_dir,
            ),
            approvals=approvals,
            hooks=reactions,
            # Read for each new session, so edits through the API apply at once.
            defaults=lambda: context.settings.agents,
            idle_close=timedelta(minutes=settings.agents.idle_close_minutes),
            clock=clock,
            live_chats=live_chats,
            queue=MessageQueue(db, clock, bus),
            models=engine.find,
            # The first local model while no engine is signed in (B106).
            default_model=lambda: local.default_or(engine.default_model),
            extras=lambda session: pixie_runtime.extras(session),
            agents=pixie_agents.for_session,
            issues=issues.fetch,
            calls=pixie_calls,
            nest_tools=lambda session: (
                *artifact_tools(artifacts, session),
                *computer_tools(computer, session),
            ),
            call_tools=lambda session, agents: call_runs.tools(session, agents),
            engines=[
                Engine(
                    CodexProvider(
                        codex_home=codex_home,
                        transport=codex_transport,
                        shell_env=shell_env,
                    ),
                    models=codex.find,
                    ready=codex.require_signed_in,
                    default=lambda: local.default_or(codex.default_model),
                    small=codex_small_model,
                    accounts=active.source(CODEX_ACCOUNTS),
                ),
                *(
                    Engine(
                        AcpProvider(
                            service.engine,
                            service.launch,
                            transport=acp_setup.transport,
                        ),
                        models=service.find,
                        ready=service.require_ready,
                        default=service.default_model,
                        small=_acp_small_model(service),
                        accounts=active.source(service.name),
                        git_guard=service.engine.git_guard,
                        can_push=can_push,
                    )
                    for service in acp.values()
                ),
            ],
            accounts=active.source(CLAUDE_ACCOUNTS),
            local=local,
            ports=runs.agent_ports,
            names_dir=paths.names_dir,
            keep_awake=KeepAwake(system.name),
            weekly_used=partial(weekly_used, usage),
            can_push=can_push,
        )
        call_runs: PixieCallRuns = PixieCallRuns(
            pixies=pixie_store,
            sessions=sessions,
            bus=bus,
            defaults=lambda: context.settings.agents,
            store=bridged_calls,
            log=pixie_calls,
            notifier=notifier,
            usage=usage.record_subagent,
        )
        sessions.bridge(call_runs)
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
            machine=system.machine_noun,
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
            habits=habits,
            store=habit_store,
            reports=reports,
            activity=activity,
            machine=system.machine_noun,
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
            can_push=can_push,
        )
        monitor = PrMonitor(
            store=store,
            bus=bus,
            approvals=approvals,
            notifier=notifier,
            run=runner,
            clock=clock,
            cwd=paths.data_dir,
            send=lambda session_id, text, sender: sessions.send(
                session_id, text, [], sender=sender
            ),
        )
        # Pull requests an agent opened itself are followed too (B101).
        pr_adopter = PrAdopter(
            store=store,
            bus=bus,
            repo=repos.get,
            run=runner,
            cwd=paths.data_dir,
            check_soon=monitor.check_soon,
        )
        followers.append(pr_adopter)
        publisher = GitPublisher(runner, store, bus, paths.data_dir)
        reviews = ReviewActions(
            sessions=sessions,
            repos=repos,
            approvals=approvals,
            tracking=tracking,
            publisher=publisher,
            prs=monitor,
            scope=review_scope,
        )
        prs = PullRequests(
            sessions=sessions,
            store=store,
            approvals=approvals,
            monitor=monitor,
            bus=bus,
            run=runner,
            cwd=paths.data_dir,
        )
        stacks = Stacks(
            store=store,
            sessions=sessions,
            approvals=approvals,
            publisher=publisher,
            repos=repos,
            monitor=monitor,
            bus=bus,
            run=runner,
            neutral_cwd=paths.data_dir,
        )
        prs.on_merged(stacks.parent_merged)
        guides = ReviewGuides(
            store=store,
            bus=bus,
            clock=clock,
            engines=sessions.engines,
            local=local,
            artifacts=artifacts,
            run=runner,
            cwd=paths.data_dir,
            folder=paths.guides_dir,
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
        devices = DeviceService(db, clock, secrets, f"This {system.machine_noun}")
        claude_code = ClaudeCli(
            locations=claude_locations or ClaudeLocations.default(Path.home(), os.environ, system),
            run=claude_runner or run_command,
            # Signing in waits on the user in the browser; installing downloads.
            run_long=claude_runner or partial(run_command, time_limit=LONG_COMMAND_SECONDS),
            cwd=paths.data_dir,
            bus=bus,
            # A cancelled sign in stops (B98).
            run_sign_in=claude_runner
            or partial(run_command, time_limit=LONG_COMMAND_SECONDS, kill_on_cancel=True),
        )
        usage_refresher = UsageRefresher(
            store=usage,
            bus=bus,
            clock=clock,
            probe=UsageProbe(probe_factory, paths.probe_dir),
            visibility=ClientVisibility(clock),
            # Read at each check, so a new interval from the API applies at once.
            interval=lambda: context.usage_interval(),
            codex=codex.usage,
            account=lambda: active.prepare(CLAUDE_ACCOUNTS),
            other_codex=lambda: accounts.read_other_codex(),
            claude_signed_in=logins.claude,
        )
        accounts = Accounts(
            store=account_store,
            active=active,
            profiles=profiles,
            usage=usage,
            refresher=usage_refresher,
            bus=bus,
            clock=clock,
            claude_cli=claude_code,
            codex=codex,
            codex_transport=codex_transport,
            codex_launch=codex_launch,
            close_idle_runs=sessions.close_idle_runs,
            claude_switched=engine.refresh,
            acp=acp,
        )
        # The shared setup is the first account's: every other one links to it (B98).
        codex_setup = CodexSetup(codex_transport, lambda: codex_launch({}))
        backups = Backups(paths.data_dir / "config-backups", clock)
        extensions = Extensions(claude_code, bus, paths.claude_dir)
        configuration = Configuration(
            where,
            backups,
            codex_setup,
            build_sources(
                claude_account=accounts.claude_active,
                claude_cli=claude_code,
                codex=codex,
                codex_locations=codex_locations
                or CodexLocations.default(
                    Path.home(), os.environ, bundled_binary().executable, system
                ),
                run=runner,
                cwd=paths.data_dir,
                extensions=extensions,
                connectors=connectors,
                repos=repos,
                settings=lambda: context.settings.configuration,
                save_settings=lambda changed: context.save_configuration_settings(changed),
                local_in_use=local.in_use,
            ),
        )
        machine_name_text = await machine()
        perf_timings = RouteTimings()
        perf, perf_fetch = build_perf(
            PerfSetup(
                paths=paths,
                db=db,
                bus=bus,
                clock=clock,
                zone=zone,
                machine=machine_name_text,
                timings=perf_timings,
                send_times=notifications.send_times.all,
                worktree_folders=lambda: _worktree_folders(paths, repos, worktrees),
                local_token=devices.ensure_local_device,
                general_prompt=PLAIN_FOLDER_PROMPT,
                general_tools=artifact_tools(artifacts, _general_stand_in(clock)),
                shell_env=shell_env,
                claude_account=lambda: active.prepare(CLAUDE_ACCOUNTS),
                claude_signed_in=logins.claude,
                context_client=perf_client,
                engines=lambda: sessions.engines,
                codex=codex,
                acp=acp,
                machine_noun=system.machine_noun,
            )
        )
        updates = UpdateService(
            paths=paths,
            platform=system.name,
            bus=bus,
            shell_env=shell_env,
            busy_chats=sessions.busy_count,
            port=lambda: context.serving_port(),
            setup=update_setup or UpdateSetup(),
            engines_wait=local.engine_updates_wait,
        )
        trigger_store = TriggerStore(db, clock)
        github_triggers = GitHubPoller(
            repos=repos.list_repos,
            habits=habit_store,
            scheduler=scheduler,
            chats=TriggeredChats(
                start=lambda request, ref: sessions.create(request, started_by_trigger=ref),
                store=trigger_store,
                usage=usage,
                clock=clock,
                # Read for each event, so edits through the API apply at once.
                pixie_settings=lambda: context.settings.pixies,
                can_push=can_push,
            ),
            store=trigger_store,
            bus=bus,
            run=runner,
            cwd=paths.data_dir,
            clock=clock,
            access=WriteAccess(runner, paths.data_dir, clock),
        )
        codex_where = codex_locations or CodexLocations.default(
            Path.home(), os.environ, bundled_binary().executable, system
        )
        outside = OutsideService(
            store=ClientStore(db, clock),
            tokens=ClientTokens(),
            config=McpConfig(
                claude=claude_code,
                codex_program=lambda: codex_where.standalone() or codex_where.bundled,
                codex_home=paths.codex_home,
                run=runner,
                cwd=paths.data_dir,
            ),
            sessions=sessions,
            session_store=store,
            approvals=approvals,
            bus=bus,
            repos=repos,
            pixies=pixies,
            teams=teams,
            clock=clock,
            zone=zone,
        )
        context = cls(
            paths=paths,
            platform=system,
            updates=updates,
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
            reactions=reactions,
            reviews=reviews,
            usage=usage,
            connectors=connectors,
            local_apps=LocalApps(opener, paths.launchers_dir, system),
            notifications=notifications,
            claude_chats=claude_chats,
            branch_watch=BranchWatch(repos=repos, bus=bus),
            review_recheck=ReviewRecheck(bus=bus, repos=repos, recheck=reactions.refs_moved),
            merged_worktrees=MergedWorktrees(
                repos=repos,
                store=store,
                worktrees=worktrees,
                remove=sessions.remove_unused_worktree,
                bus=bus,
            ),
            places=places,
            fetcher=RepoFetcher(bus),
            usage_refresher=usage_refresher,
            commands=commands,
            prs=prs,
            stacks=stacks,
            guides=guides,
            search=search,
            issues=issues,
            pr_adopter=pr_adopter,
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
            acp=acp,
            sign_ins=sign_ins,
            chat_defaults=ChatDefaults(lambda: sessions.engines, sign_ins, local.engine),
            pixies=pixies,
            pixie_calls=pixie_calls,
            pixie_call_runs=call_runs,
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
                memory_files=memory_files(paths.home, paths.claude_dir, paths.codex_home),
                pixie_files=pixie_files,
                clock=clock,
                shell_env=shell_env,
                shell=shell,
                base_env=os.environ,
            ),
            archiver=ChatArchiver(
                sessions=sessions,
                approvals=approvals,
                claude_chats=claude_chats,
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
            chat_triggers=ChatTriggerService(repos, trigger_store),
            github_triggers=github_triggers,
            claude_code=claude_code,
            accounts=accounts,
            extensions=extensions,
            artifacts=artifacts,
            computer=computer,
            voice=VoiceService(
                paths.voice_dir, system.name, lambda: context.settings.voice, voice_setup
            ),
            configuration=configuration,
            project_setup=ProjectSetup(backups),
            codex_plugins=CodexPluginSetup(codex_setup),
            configuration_watcher=ConfigurationWatcher(
                bus, where, lambda: {repo.name: repo.path for repo in repos.list_repos()}
            ),
            features=Features(
                FeatureStore(db, clock), clock, zone, packaged_catalog().for_platform(system.name)
            ),
            # Each request gets the current token: a revoked local device is given a new one.
            token_socket=None
            if paths.token_socket is None
            else TokenSocket(paths.token_socket, devices.ensure_local_device),
            outside=outside,
            outside_socket=None
            if paths.outside_socket is None
            else ClientSocket(paths.outside_socket, outside.issue_token),
            machine=machine_name_text,
            local=local,
            runs=runs,
            perf=perf,
            perf_timings=perf_timings,
            perf_fetch=perf_fetch,
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
        # With no engine signed in they are provisional (B106): a local model added later,
        # or an engine signed in, picks them then.
        keep = resolved.complete and stored != concrete and await self.local.engine_signed_in()
        try:
            if keep:
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
        # A local model stands in only while no engine is signed in (B106): not kept.
        if model is not None and not is_local(model):
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
        # First, so the browser and emulators it started stop even if a slow step after it
        # is cut short.
        await self.computer.close()
        await self.voice.close()
        await self.local.close()
        await self.accounts.stop()
        for service in self.acp.values():
            await service.install.stop()
        await self.claude_code.stop()
        await self.modules.stop_all()
        await self.notifications.close()
        await self.db.close()


async def _has_chats(db: Database) -> bool:
    return await db.fetch_one("SELECT 1 FROM sessions LIMIT 1") is not None


def _acp_small_model(service: AcpEngineService) -> Callable[[], Awaitable[str | None]]:
    async def small_model() -> str | None:
        return cheapest((await service.models()).models)

    return small_model


def _locations(paths: AppPaths) -> Locations | None:
    """The engines' folders; None when Nest was started without one (tests)."""
    if paths.claude_dir is None or paths.claude_account_file is None or paths.codex_home is None:
        return None
    return Locations(paths.claude_dir, paths.claude_account_file, paths.codex_home)


def _worktree_folders(
    paths: AppPaths, repos: RepoService, worktrees: WorktreeManager
) -> list[Path]:
    """Where Nest's worktrees are: each repo's `nest-*` in its worktrees folder and, after
    a move to another, in `.claude/worktrees` (B141), and the old folder.
    """
    # The old folder counts only while it still holds a worktree.
    folders = [paths.worktrees_dir] if any(paths.worktrees_dir.glob("*")) else []
    for repo in repos.list_repos():
        places = dict.fromkeys((worktrees.options(repo).folder, claude_worktrees_dir(repo.path)))
        for place in places:
            folders += (path for path in place.glob(f"{WORKTREE_PREFIX}*") if path.is_dir())
    return folders


def _general_stand_in(clock: Clock) -> Session:
    """A new General chat, only for the Nest tools a chat gets (B115): the performance
    run lists them to the engine but never calls them."""
    now = clock.now()
    return Session.model_construct(
        id="perf-context",
        repo=GENERAL,
        title="Performance check",
        pixie_id=None,
        created_at=now,
        updated_at=now,
    )


async def _engine_of(store: SessionStore, session_id: str) -> str:
    """A chat's engine, for continuing the pixies it called its own way (B112)."""
    return (await store.get(session_id)).provider
