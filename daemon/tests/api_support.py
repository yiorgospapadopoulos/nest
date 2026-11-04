"""Helpers for building a daemon app around a temporary context."""

from datetime import UTC
from pathlib import Path

import httpx
from claude_agent_sdk import ClaudeAgentOptions

from nestd.auth.devices import LOCAL_DEVICE_ACCOUNT
from nestd.configuration.engines import CodexLocations
from nestd.context import AppContext
from nestd.gitops.runner import CommandRunner, run_command
from nestd.local.service import LocalSetup
from nestd.paths import AppPaths
from nestd.perf.collectors.context import ContextClient
from nestd.platform import MACOS
from nestd.providers.acp_process import AcpTransportFactory
from nestd.providers.base import AgentProvider
from nestd.providers.shell_env import no_shell_env
from tests.acp_engine_support import FakeNpm, acp_setup
from tests.codex_support import FakeAppServer
from tests.db_support import migrated_copy
from tests.fake_claude import FakeClaude, locations
from tests.fake_engine import FakeInfoFactory
from tests.fake_opener import FakeOpener
from tests.fake_probe import FakeProbeFactory
from tests.fake_provider import FakeProvider
from tests.fakes import FakeClock, FakeSecretStore
from tests.local_support import LocalMac
from tests.push_support import no_network


class RecordingModule:
    name = "recorder"

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def start(self, ctx: AppContext) -> None:
        self._log.append(f"start {ctx.settings.server.port}")

    async def stop(self) -> None:
        self._log.append("stop")


async def as_old_chats(ctx: AppContext, *session_ids: object) -> None:
    """Chats from before B119, which close on merge and take their worktree when deleted."""
    for session_id in session_ids:
        await ctx.db.execute("UPDATE sessions SET movable = 0 WHERE id = ?", (str(session_id),))


def make_paths(
    tmp_path: Path,
    modules: list[str] | None = None,
    token_socket: Path | None = None,
    codex_home: Path | None = None,
) -> AppPaths:
    # No web build, so API tests never depend on whether web/dist exists in the checkout.
    paths = AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        web_dist=tmp_path / "web",
        claude_dir=tmp_path / "claude",
        claude_account_file=tmp_path / "claude.json",
        token_socket=token_socket,
        codex_home=codex_home,
    )
    if modules is not None:
        paths.config_dir.mkdir(parents=True)
        enabled = ", ".join(f'"{name}"' for name in modules)
        paths.settings_file.write_text(f"[modules]\nenabled = [{enabled}]\n", encoding="utf-8")
    return paths


async def build_context(
    tmp_path: Path,
    clock: FakeClock,
    secrets: FakeSecretStore,
    log: list[str] | None = None,
    provider: AgentProvider | None = None,
    runner: CommandRunner = run_command,
    opener: CommandRunner | None = None,
    push_transport: httpx.AsyncBaseTransport | None = None,
    probe_factory: FakeProbeFactory | None = None,
    engine_factory: FakeInfoFactory | None = None,
    token_socket: Path | None = None,
    claude: FakeClaude | None = None,
    codex: FakeAppServer | None = None,
    codex_home: Path | None = None,
    local_setup: LocalSetup | None = None,
    npm: FakeNpm | None = None,
    acp: AcpTransportFactory | None = None,
) -> AppContext:
    record = log if log is not None else []
    paths = make_paths(
        tmp_path, ["recorder"] if log is not None else None, token_socket, codex_home
    )
    # A database already there, as after a restart, is kept.
    if not paths.db_path.exists():
        await migrated_copy(paths.db_path)
    return await AppContext.build(
        paths,
        secrets,
        clock,
        {"recorder": lambda: RecordingModule(record)},
        provider=provider or FakeProvider(),
        runner=runner,
        # Never the real `open`; usage days by UTC, so tests do not depend on the machine.
        opener=opener or FakeOpener(),
        zone=UTC,
        push_transport=push_transport or no_network(),
        # Never a real Claude probe; without scripted replies every probe fails.
        probe_factory=probe_factory or FakeProbeFactory(),
        # Never a real Claude Code process for the model list.
        engine_factory=engine_factory or FakeInfoFactory(),
        # Never the user's real login shell.
        shell_env=no_shell_env,
        # Never the real `claude` command line, nor the user's installs.
        claude_runner=claude or FakeClaude(),
        claude_locations=locations(tmp_path),
        # Never the real Codex binary.
        codex_transport=codex or FakeAppServer(),
        # Nor a standalone Codex on this Mac.
        codex_locations=codex_locations(tmp_path),
        # Never the real machine's name.
        machine=fake_machine_name,
        # Never a real model server, the user's model folders or a started app.
        local_setup=local_setup or LocalMac(tmp_path / "local").setup(),
        # Never the real lsof.
        port_probe=nothing_listening,
        # Never real npm, engine processes, PATH or home (B107).
        acp_setup=acp_setup(tmp_path, npm, acp),
        # Never a real Claude turn for Settings > Performance (B115).
        perf_client=no_context_client,
        # The same apps and folders on every system the tests run on (B117).
        platform=MACOS,
    )


def no_context_client(_options: ClaudeAgentOptions) -> ContextClient:
    msg = "a test reached the performance context run's Claude client"
    raise AssertionError(msg)


async def fake_machine_name() -> str:
    return "Test Mac"


async def nothing_listening(_group: int) -> list[int]:
    return []


def codex_locations(tmp_path: Path) -> CodexLocations:
    """No standalone Codex; Nest's own is version 0.163.0."""
    return CodexLocations(
        search_path="",
        candidates=(tmp_path / "home" / ".local" / "bin" / "codex",),
        bundled=None,
        bundled_version="0.163.0",
    )


def local_token(secrets: FakeSecretStore) -> str:
    token = secrets.get(LOCAL_DEVICE_ACCOUNT)
    assert token is not None
    return token
