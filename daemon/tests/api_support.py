"""Helpers for building a daemon app around a temporary context."""

from datetime import UTC
from pathlib import Path

import httpx

from nestd.auth.devices import LOCAL_DEVICE_ACCOUNT
from nestd.configuration.engines import CodexLocations
from nestd.context import AppContext
from nestd.gitops.runner import CommandRunner, run_command
from nestd.local.service import LocalSetup
from nestd.paths import AppPaths
from nestd.providers.base import AgentProvider
from nestd.providers.shell_env import no_shell_env
from tests.codex_support import FakeAppServer
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
) -> AppContext:
    record = log if log is not None else []
    return await AppContext.build(
        make_paths(tmp_path, ["recorder"] if log is not None else None, token_socket, codex_home),
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
    )


async def fake_machine_name() -> str:
    return "Test Mac"


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
