"""Helpers for building a daemon app around a temporary context."""

from datetime import UTC
from pathlib import Path

from harness.auth.devices import LOCAL_DEVICE_ACCOUNT
from harness.context import AppContext
from harness.gitops.runner import CommandRunner, run_command
from harness.paths import AppPaths
from harness.providers.base import AgentProvider
from tests.fake_opener import FakeOpener
from tests.fake_provider import FakeProvider
from tests.fakes import FakeClock, FakeSecretStore


class RecordingModule:
    name = "recorder"

    def __init__(self, log: list[str]) -> None:
        self._log = log

    async def start(self, ctx: AppContext) -> None:
        self._log.append(f"start {ctx.settings.server.port}")

    async def stop(self) -> None:
        self._log.append("stop")


def make_paths(tmp_path: Path, modules: list[str] | None = None) -> AppPaths:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
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
) -> AppContext:
    record = log if log is not None else []
    return await AppContext.build(
        make_paths(tmp_path, ["recorder"] if log is not None else None),
        secrets,
        clock,
        {"recorder": lambda: RecordingModule(record)},
        provider=provider or FakeProvider(),
        runner=runner,
        # Never the real `open`; usage days by UTC, so tests do not depend on the machine.
        opener=opener or FakeOpener(),
        zone=UTC,
    )


def local_token(secrets: FakeSecretStore) -> str:
    token = secrets.get(LOCAL_DEVICE_ACCOUNT)
    assert token is not None
    return token
