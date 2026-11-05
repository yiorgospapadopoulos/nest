"""The performance service with a collector for every daemon section (B115)."""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import tzinfo
from pathlib import Path

from nestd.clock import Clock
from nestd.engine.acp import AcpEngineService
from nestd.engine.codex import CodexEngine
from nestd.events.bus import EventBus
from nestd.paths import AppPaths
from nestd.perf.build import current_build
from nestd.perf.collectors import Collector
from nestd.perf.collectors.activity import Activity
from nestd.perf.collectors.context import ContextClientFactory, ContextCost, NewChat
from nestd.perf.collectors.daemon import Daemon
from nestd.perf.collectors.engines import Engines, Target
from nestd.perf.collectors.gates import Gates
from nestd.perf.collectors.load import InProcess, LoadSpeed
from nestd.perf.collectors.pixies import Pixies
from nestd.perf.collectors.reliability import Reliability
from nestd.perf.collectors.subagents import Subagents
from nestd.perf.collectors.turns import TurnSpeed
from nestd.perf.collectors.waiting import Waiting
from nestd.perf.collectors.worktrees import Worktrees
from nestd.perf.gate_times import GateTimes
from nestd.perf.service import Perf
from nestd.perf.store import PerfStore
from nestd.perf.timing import RouteTimings
from nestd.providers.base import AgentTool, RunAccount
from nestd.providers.one_off import cheapest
from nestd.sessions.engines import Engines as ChatEngines
from nestd.storage.db import Database

# The cheapest Claude model, as the usage probe uses.
CLAUDE_MODEL = "haiku"


@dataclass(frozen=True)
class PerfSetup:
    """What the collectors reach beyond the database."""

    paths: AppPaths
    db: Database
    bus: EventBus
    clock: Clock
    zone: tzinfo | None
    machine: str
    timings: RouteTimings
    send_times: Callable[[], list[float]]
    # The folders Nest's worktrees are in, read at each run.
    worktree_folders: Callable[[], Iterable[Path]]
    local_token: Callable[[], Awaitable[str]]
    # A new General chat's prompt and Nest tools.
    general_prompt: str
    general_tools: tuple[AgentTool, ...]
    shell_env: Callable[[], Awaitable[Mapping[str, str]]]
    claude_account: Callable[[], Awaitable[RunAccount | None]]
    claude_signed_in: Callable[[], Awaitable[bool]]
    context_client: ContextClientFactory
    engines: Callable[[], ChatEngines]
    codex: CodexEngine
    acp: Mapping[str, AcpEngineService]
    # The machine in text for people, as in "this Mac".
    machine_noun: str = "Mac"


def build_perf(setup: PerfSetup) -> tuple[Perf, InProcess]:
    """The service, and the in-process client the API is attached to once it exists."""
    store = PerfStore(setup.db, setup.clock)
    fetch = InProcess(setup.local_token)
    paths = setup.paths
    claude_dir = paths.claude_dir
    collectors: dict[str, Collector] = {
        "context": ContextCost(
            NewChat(
                folder=paths.general_dir,
                prompt=setup.general_prompt,
                tools=setup.general_tools,
                gh_config_dir=paths.agent_gh_dir,
                shell_env=setup.shell_env,
                account=setup.claude_account,
            ),
            setup.context_client,
            claude_md=(
                (claude_dir or paths.data_dir / "no-claude") / "CLAUDE.md",
                paths.general_dir / "CLAUDE.md",
            ),
        ),
        "turns": TurnSpeed(setup.db, setup.clock),
        "load": LoadSpeed(setup.db, setup.bus, fetch),
        "waiting": Waiting(setup.db, setup.clock, setup.send_times),
        "activity": Activity(setup.db, setup.clock, setup.zone),
        "pixies": Pixies(setup.db, setup.clock),
        "subagents": Subagents(setup.db, setup.clock),
        "reliability": Reliability(setup.db, setup.clock, store.starts_since),
        "engines": Engines(lambda: _targets(setup), paths.data_dir / "perf"),
        "daemon": Daemon(
            setup.db,
            paths.db_path,
            paths.attachments_dir,
            setup.worktree_folders,
            store.latest_start,
            setup.timings,
        ),
        "worktrees": Worktrees(setup.db, setup.clock),
        "gates": Gates(GateTimes.in_folder(paths.data_dir)),
    }
    return Perf(
        store,
        setup.bus,
        setup.clock,
        collectors,
        current_build(),
        setup.machine,
        setup.machine_noun,
    ), fetch


async def _targets(setup: PerfSetup) -> list[Target]:
    """The engines signed in now, on the subscription: local models are left out."""
    engines = setup.engines()
    targets: list[Target] = []

    async def claude_model() -> str | None:
        return CLAUDE_MODEL

    if await setup.claude_signed_in():
        targets.append(Target(engines.default.provider, claude_model, setup.claude_account))
    codex = setup.codex
    if (await codex.status()).signed_in is True:
        engine = engines.by_name("codex")

        async def codex_model() -> str | None:
            return cheapest((await codex.models()).models)

        targets.append(Target(engine.provider, codex_model, engine.prepare_account))
    for name, service in setup.acp.items():
        if (await service.status()).signed_in is not True:
            continue
        engine = engines.by_name(name)

        async def acp_model(service: AcpEngineService = service) -> str | None:
            return cheapest((await service.models()).models)

        targets.append(Target(engine.provider, acp_model, engine.prepare_account))
    return targets
