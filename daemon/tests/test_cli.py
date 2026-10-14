import io
import logging
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest
from fastapi import FastAPI

from harness.auth.devices import LOCAL_DEVICE_ACCOUNT
from harness.auth.secrets import KeychainSecretStore
from harness.cli import main
from harness.clock import SystemClock
from harness.paths import AppPaths
from harness.runtime import Runtime, default_runtime
from harness.server import run_uvicorn
from harness.service.launchd import LABEL, CommandResult, run_command
from tests.fakes import FakeClock, FakeSecretStore


class Recorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.served: list[int] = []
        self.print_result = CommandResult(113, "", "Could not find service")
        self.bootstrap_result = CommandResult(0, "", "")

    def run(self, args: Sequence[str]) -> CommandResult:
        self.commands.append(list(args))
        if args[1] == "print":
            return self.print_result
        if args[1] == "bootstrap":
            return self.bootstrap_result
        return CommandResult(0, "", "")

    async def serve(self, app: FastAPI, port: int) -> None:
        # Run the real startup and shutdown so the app is exercised in this event loop.
        async with app.router.lifespan_context(app):
            self.served.append(port)


class Harness:
    def __init__(self, tmp_path: Path, data_dir: Path) -> None:
        self.home = tmp_path / "home"
        self.env = {
            "HARNESS_CONFIG_DIR": str(tmp_path / "config"),
            "HARNESS_DATA_DIR": str(data_dir),
        }
        self.paths = AppPaths.from_env(self.env, self.home)
        self.recorder = Recorder()
        self.secrets = FakeSecretStore()
        self.out = io.StringIO()
        self.err = io.StringIO()
        self.runtime = Runtime(
            env=self.env,
            home=self.home,
            uid=501,
            executable="/venv/bin/python",
            secrets=self.secrets,
            clock=FakeClock(),
            run_command=self.recorder.run,
            serve=self.recorder.serve,
            out=self.out,
            err=self.err,
        )

    def run(self, *argv: str) -> int:
        return main(list(argv), self.runtime)


@pytest.fixture
def cli(tmp_path: Path) -> Iterator[Harness]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    # Short, since `serve` opens the token socket in the data folder (D075) and Unix socket
    # paths are limited to about 104 bytes; pytest's tmp_path can be longer.
    data_root = Path(tempfile.mkdtemp(prefix="hx-", dir="/tmp"))
    yield Harness(tmp_path, data_root / "data")
    shutil.rmtree(data_root)
    root.handlers[:] = handlers
    root.setLevel(level)


def test_default_runtime_uses_the_real_system() -> None:
    runtime = default_runtime()

    assert runtime.home == Path.home()
    assert isinstance(runtime.secrets, KeychainSecretStore)
    assert isinstance(runtime.clock, SystemClock)
    assert runtime.run_command is run_command
    assert runtime.serve is run_uvicorn


def test_serve_uses_configured_port_and_runs_the_app(cli: Harness) -> None:
    assert cli.run("serve") == 0

    assert cli.recorder.served == [8765]
    assert cli.secrets.get(LOCAL_DEVICE_ACCOUNT)
    assert cli.paths.db_path.is_file()


def test_serve_port_flag_overrides_settings(cli: Harness) -> None:
    assert cli.run("serve", "--port", "9100") == 0

    assert cli.recorder.served == [9100]


def test_config_errors_are_reported_without_a_traceback(cli: Harness) -> None:
    cli.paths.config_dir.mkdir(parents=True)
    cli.paths.settings_file.write_text("[server\n", encoding="utf-8")

    assert cli.run("serve") == 1

    assert cli.err.getvalue().startswith("harness: ")
    assert "settings.toml: invalid TOML" in cli.err.getvalue()
    assert cli.recorder.served == []


def test_service_install(cli: Harness) -> None:
    assert cli.run("service", "install") == 0

    plist = cli.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert plist.is_file()
    assert "/venv/bin/python" in plist.read_text(encoding="utf-8")
    assert str(cli.home / ".local" / "bin") in plist.read_text(encoding="utf-8")
    assert cli.recorder.commands[-1] == ["/bin/launchctl", "bootstrap", "gui/501", str(plist)]
    assert f"Installed and started {LABEL}" in cli.out.getvalue()


def test_service_install_failure(cli: Harness) -> None:
    cli.recorder.bootstrap_result = CommandResult(5, "", "Input/output error")

    assert cli.run("service", "install") == 1

    assert "launchctl bootstrap failed" in cli.err.getvalue()


def test_service_uninstall(cli: Harness) -> None:
    cli.run("service", "install")

    assert cli.run("service", "uninstall") == 0

    assert not (cli.home / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()
    assert f"Stopped and removed {LABEL}" in cli.out.getvalue()


def test_service_status_running(cli: Harness) -> None:
    cli.run("service", "install")
    cli.recorder.print_result = CommandResult(0, "state = running\n", "")

    assert cli.run("service", "status") == 0

    output = cli.out.getvalue()
    assert "installed: yes" in output
    assert "loaded: yes" in output
    assert "state = running" in output


def test_service_status_not_installed(cli: Harness) -> None:
    assert cli.run("service", "status") == 1

    output = cli.out.getvalue()
    assert "installed: no" in output
    assert "loaded: no" in output


def test_pair_prints_a_code_and_its_expiry(cli: Harness) -> None:
    assert cli.run("pair") == 0

    lines = cli.out.getvalue().splitlines()
    assert lines[0].startswith("Pairing code: ")
    assert len(lines[0].removeprefix("Pairing code: ")) == 8
    assert lines[1].startswith("Expires at ")


def test_a_command_is_required(cli: Harness) -> None:
    with pytest.raises(SystemExit) as exited:
        cli.run()

    assert exited.value.code == 2
