import io
import logging
import os
import shutil
import tempfile
from collections.abc import Awaitable, Callable, Iterator, Mapping, Sequence
from dataclasses import replace
from functools import partial
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI

from nestd import __version__
from nestd.accounts.profiles import LEAKED_ENV
from nestd.auth.devices import LOCAL_DEVICE_ACCOUNT
from nestd.auth.secrets import SecretStoreUnavailableError
from nestd.cli import main
from nestd.paths import AppPaths
from nestd.platform import LINUX, MACOS, Platform
from nestd.runtime import Runtime
from nestd.service.base import CommandResult
from nestd.service.launchd import LABEL
from nestd.service.restart import terminate_self
from nestd.service.systemd import UNIT_NAME
from nestd.updates.app import STARTS_NAME, note_start, starts_of
from nestd.updates.boot import installed_fingerprint
from nestd.updates.state import BASE, StateFile, UpdateState
from tests.fakes import FakeClock, FakeSecretStore, RecordingRestart
from tests.updates_support import make_environment


class Recorder:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.served: list[int] = []
        self.switched: list[list[str]] = []
        self.print_result = CommandResult(113, "", "Could not find service")
        self.bootstrap_result = CommandResult(0, "", "")
        # Called inside the served app, as a client would act while the daemon runs.
        self.while_serving: list[Callable[[FastAPI], Awaitable[None]]] = []

    def exec_program(self, program: str, args: list[str], _env: Mapping[str, str]) -> None:
        self.switched.append([program, *args[1:]])

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
            for action in self.while_serving:
                await action(app)


class LockedSecretStore(FakeSecretStore):
    def get(self, account: str) -> str | None:
        msg = "the secret store is not available (locked). Unlock the login keyring."
        raise SecretStoreUnavailableError(msg)


class Rig:
    def __init__(self, home: Path, env: dict[str, str], platform: Platform = MACOS) -> None:
        self.home = home
        self.env = env
        self.paths = AppPaths.from_env(self.env, self.home, platform)
        self.recorder = Recorder()
        self.secrets: FakeSecretStore = FakeSecretStore()
        self.restart = RecordingRestart()
        self.out = io.StringIO()
        self.err = io.StringIO()
        self.runtime = Runtime(
            env=self.env,
            home=self.home,
            uid=501,
            executable="/venv/bin/python",
            prefix=home / "venv",
            exec_program=self.recorder.exec_program,
            platform=platform,
            secrets=self.secrets,
            clock=FakeClock(),
            run_command=self.recorder.run,
            serve=self.recorder.serve,
            restart=self.restart,
            out=self.out,
            err=self.err,
        )

    def run(self, *argv: str) -> int:
        return main(list(argv), self.runtime)


@pytest.fixture
def cli(tmp_path: Path) -> Iterator[Rig]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    # Short, since `serve` opens the token socket in the data folder (D075) and Unix socket
    # paths are limited to about 104 bytes; pytest's tmp_path can be longer.
    data_root = Path(tempfile.mkdtemp(prefix="hx-", dir="/tmp"))
    env = {"NEST_CONFIG_DIR": str(tmp_path / "config"), "NEST_DATA_DIR": str(data_root / "data")}
    yield Rig(tmp_path / "home", env)
    shutil.rmtree(data_root)
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.fixture
def moving() -> Iterator[Rig]:
    """B43: no variables, so the default folders are used, with harness's still there."""
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    home = Path(tempfile.mkdtemp(prefix="hx-", dir="/tmp"))
    old_config = home / ".config" / "harness"
    (old_config / "repos").mkdir(parents=True)
    (old_config / "settings.toml").write_text("[server]\nport = 9200\n", encoding="utf-8")
    old_data = home / "Library" / "Application Support" / "harness"
    old_data.mkdir(parents=True)
    (old_data / "attachments").mkdir()
    yield Rig(home, {})
    shutil.rmtree(home)
    root.handlers[:] = handlers
    root.setLevel(level)


def test_serve_moves_to_the_environment_that_should_run(cli: Rig) -> None:
    root = cli.paths.environments_dir
    root.mkdir(parents=True)
    make_environment(root, "aaaaaaaaaaaa", fingerprint=installed_fingerprint())
    StateFile(root).save(UpdateState(current="aaaaaaaaaaaa", previous=BASE))

    cli.run("serve", "--port", "9100")

    python = str(root / "aaaaaaaaaaaa" / "bin" / "python")
    assert cli.recorder.switched == [[python, "-m", "nestd", "serve", "--port", "9100"]]


def test_serve_uses_configured_port_and_runs_the_app(cli: Rig) -> None:
    assert cli.run("serve") == 0

    assert cli.recorder.served == [8765]
    assert cli.secrets.get(LOCAL_DEVICE_ACCOUNT)
    assert cli.paths.db_path.is_file()


def test_serve_drops_the_account_variables_a_claude_shell_leaks(
    cli: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B98: inherited by every engine process, they make an added account show another."""
    for name in LEAKED_ENV:
        monkeypatch.setenv(name, "leaked")

    assert cli.run("serve") == 0

    assert [name for name in LEAKED_ENV if name in os.environ] == []


def test_served_app_restarts_through_the_runtime(cli: Rig) -> None:
    async def ask_for_restart(app: FastAPI) -> None:
        transport = httpx.ASGITransport(app=app)
        token = cli.secrets.get(LOCAL_DEVICE_ACCOUNT)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
            response = await http.post(
                "/api/service/restart", headers={"Authorization": f"Bearer {token}"}
            )
        assert response.status_code == 202

    cli.recorder.while_serving.append(ask_for_restart)

    assert cli.run("serve") == 0

    assert cli.restart.calls == 1


def _packaged(cli: Rig, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr("nestd.cli.is_packaged", lambda: True)
    folder = cli.paths.daemon_dir / __version__
    folder.mkdir(parents=True)
    return folder / STARTS_NAME


def test_a_restart_is_marked_clean_before_the_daemon_is_ended(
    cli: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B159 recheck 2 D: uvicorn re-raises SIGTERM, so a marker written after the server
    stopped never was, and three Restarts soon after an update rolled it back."""
    starts = _packaged(cli, monkeypatch)
    at_kill: list[int] = []

    def kill(_pid: int, _signal: int) -> None:
        at_kill.append(starts_of(cli.paths.daemon_dir, __version__))
        note_start(cli.paths.daemon_dir, __version__)

    cli.runtime = replace(cli.runtime, restart=partial(terminate_self, kill=kill))

    async def ask_for_restart(app: FastAPI) -> None:
        token = cli.secrets.get(LOCAL_DEVICE_ACCOUNT)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1") as http:
            await http.post("/api/service/restart", headers={"Authorization": f"Bearer {token}"})

    cli.recorder.while_serving.append(ask_for_restart)

    assert cli.run("serve") == 0

    assert at_kill == [1]
    assert starts.read_text(encoding="utf-8").splitlines() == ["start", "stop", "start"]
    assert starts_of(cli.paths.daemon_dir, __version__) == 1


def test_a_daemon_that_exits_on_its_own_still_counts_as_a_crash(
    cli: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    starts = _packaged(cli, monkeypatch)

    assert cli.run("serve") == 0

    assert starts.read_text(encoding="utf-8").splitlines() == ["start"]


def test_serve_port_flag_overrides_settings(cli: Rig) -> None:
    ports: list[int] = []

    async def note_port(app: FastAPI) -> None:
        ports.append(app.state.ctx.serving_port())

    cli.recorder.while_serving.append(note_port)

    assert cli.run("serve", "--port", "9100") == 0

    assert cli.recorder.served == [9100]
    # Local models' runs reach the daemon's proxy on the port it serves on (B106).
    assert ports == [9100]


def test_without_the_port_flag_the_daemon_serves_on_the_configured_port(cli: Rig) -> None:
    ports: list[int] = []

    async def note_port(app: FastAPI) -> None:
        ports.append(app.state.ctx.serving_port())

    cli.recorder.while_serving.append(note_port)

    assert cli.run("serve") == 0

    assert ports == cli.recorder.served


def test_config_errors_are_reported_without_a_traceback(cli: Rig) -> None:
    cli.paths.config_dir.mkdir(parents=True)
    cli.paths.settings_file.write_text("[server\n", encoding="utf-8")

    assert cli.run("serve") == 1

    assert cli.err.getvalue().startswith("nestd: ")
    assert "settings.toml: invalid TOML" in cli.err.getvalue()
    assert cli.recorder.served == []


def test_service_install(cli: Rig) -> None:
    assert cli.run("service", "install") == 0

    plist = cli.home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert plist.is_file()
    assert "/venv/bin/python" in plist.read_text(encoding="utf-8")
    assert str(cli.home / ".local" / "bin") in plist.read_text(encoding="utf-8")
    assert cli.recorder.commands[-1] == ["/bin/launchctl", "bootstrap", "gui/501", str(plist)]
    assert f"Installed and started {LABEL}" in cli.out.getvalue()


def test_service_install_failure(cli: Rig) -> None:
    cli.recorder.bootstrap_result = CommandResult(5, "", "Input/output error")

    assert cli.run("service", "install") == 1

    assert "launchctl bootstrap failed" in cli.err.getvalue()


def test_service_uninstall(cli: Rig) -> None:
    cli.run("service", "install")

    assert cli.run("service", "uninstall") == 0

    assert not (cli.home / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()
    assert f"Stopped and removed {LABEL}" in cli.out.getvalue()


def test_pair_prints_a_code_and_its_expiry(cli: Rig) -> None:
    assert cli.run("pair") == 0

    lines = cli.out.getvalue().splitlines()
    assert lines[0].startswith("Pairing code: ")
    assert len(lines[0].removeprefix("Pairing code: ")) == 8
    assert lines[1].startswith("Expires at ")


def test_serve_moves_the_folders_from_before_the_rename_first(moving: Rig) -> None:
    assert moving.run("serve") == 0

    config, data = moving.home / ".config", moving.home / "Library" / "Application Support"
    assert moving.recorder.served == [9200]
    assert (config / "harness").readlink() == config / "nest"
    assert (data / "harness").readlink() == data / "nest"
    assert (data / "harness.harness-backup" / "attachments").is_dir()
    assert moving.paths.db_path == data / "nest" / "nest.db"
    assert moving.paths.db_path.is_file()
    assert f"Moved {data / 'harness'} to {data / 'nest'}" in moving.err.getvalue()
    assert moving.run("serve") == 0


def test_serve_stops_with_a_clear_line_when_a_folder_cannot_move(moving: Rig) -> None:
    (moving.home / ".config" / "harness.harness-backup").mkdir()

    assert moving.run("serve") == 1

    assert moving.err.getvalue().startswith("nestd: ")
    assert "already exists" in moving.err.getvalue()
    assert moving.recorder.served == []
    assert not (moving.home / ".config" / "nest").exists()
    assert not (moving.home / ".config" / "harness").is_symlink()


def test_serve_adopts_the_old_database_in_a_folder_named_by_the_old_variable(
    tmp_path: Path,
) -> None:
    data_root = Path(tempfile.mkdtemp(prefix="hx-", dir="/tmp"))
    data = data_root / "data"
    data.mkdir()
    (data / "harness.db").write_bytes(b"")
    rig = Rig(
        tmp_path / "home",
        {"HARNESS_CONFIG_DIR": str(tmp_path / "c"), "HARNESS_DATA_DIR": str(data)},
    )

    try:
        assert rig.run("serve") == 0
    finally:
        shutil.rmtree(data_root)

    assert "Renamed harness.db to nest.db in" in rig.err.getvalue()


def test_service_install_replaces_the_harness_service_and_moves_the_folders(moving: Rig) -> None:
    agents = moving.home / "Library" / "LaunchAgents"
    agents.mkdir(parents=True)
    (agents / "com.harness.daemon.plist").write_text("<plist/>", encoding="utf-8")

    assert moving.run("service", "install") == 0

    assert not (agents / "com.harness.daemon.plist").exists()
    assert (agents / f"{LABEL}.plist").is_file()
    commands = moving.recorder.commands
    assert commands[0] == ["/bin/launchctl", "bootout", "gui/501/com.harness.daemon"]
    assert commands[-1][1] == "bootstrap"
    data = moving.home / "Library" / "Application Support"
    assert (data / "harness").is_symlink()
    output = moving.out.getvalue()
    assert "Removed the service from before the rename (com.harness.daemon)" in output
    assert f"Moved {data / 'harness'} to {data / 'nest'}" in output


def test_a_locked_secret_store_stops_serve_with_what_to_do(cli: Rig) -> None:
    """B117: a missing or locked Secret Service on Linux is one clear line, not a
    traceback from inside the server's startup."""
    runtime = replace(cli.runtime, secrets=LockedSecretStore())

    assert main(["serve"], runtime) == 1

    assert cli.err.getvalue() == (
        "nestd: the secret store is not available (locked). Unlock the login keyring.\n"
    )
    assert cli.recorder.served == []


class UnlockingSecretStore(FakeSecretStore):
    """Locked for its first `times` reads, as at login before the keyring opens."""

    def __init__(self, times: int) -> None:
        super().__init__()
        self.left = times

    def get(self, account: str) -> str | None:
        if self.left > 0:
            self.left -= 1
            raise SecretStoreUnavailableError("locked", locked=True)
        return super().get(account)


def test_a_keyring_still_locked_at_login_is_waited_for(
    cli: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B136: the service started before the login keyring opened and failed that start."""
    monkeypatch.setattr("nestd.cli.KEYRING_WAIT_SECONDS", 0)
    runtime = replace(cli.runtime, secrets=UnlockingSecretStore(times=2))

    assert main(["serve"], runtime) == 0

    assert cli.recorder.served == [8765]


@pytest.fixture
def linux(tmp_path: Path) -> Rig:
    """B117: Linux with no variables, so the XDG defaults under home are used."""
    return Rig(tmp_path / "home", {}, LINUX)


def test_linux_service_install_status_and_uninstall_use_systemd(linux: Rig) -> None:
    unit = linux.home / ".config" / "systemd" / "user" / UNIT_NAME

    assert linux.run("service", "install") == 0
    assert linux.run("service", "status") == 0
    assert linux.run("service", "uninstall") == 0

    assert linux.recorder.commands == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", UNIT_NAME],
        ["systemctl", "--user", "restart", UNIT_NAME],
        ["systemctl", "--user", "status", "--no-pager", UNIT_NAME],
        ["systemctl", "--user", "disable", "--now", UNIT_NAME],
        ["systemctl", "--user", "daemon-reload"],
    ]
    assert not unit.exists()
    output = linux.out.getvalue()
    assert f"Installed and started nest ({unit})" in output
    assert f"Logs: {linux.home / '.local' / 'share' / 'nest' / 'logs' / 'daemon.log'}" in output
    assert "Stopped and removed nest" in output


def test_linux_leaves_folders_named_harness_alone(linux: Rig) -> None:
    old_config = linux.home / ".config" / "harness"
    old_config.mkdir(parents=True)
    old_data = linux.home / ".local" / "share" / "harness"
    old_data.mkdir(parents=True)

    assert linux.run("pair") == 0

    assert old_config.is_dir()
    assert not old_config.is_symlink()
    assert not old_data.is_symlink()
    assert "Moved" not in linux.out.getvalue()


def test_pair_moves_the_folders_first(moving: Rig) -> None:
    assert moving.run("pair") == 0

    assert (moving.home / ".config" / "harness").is_symlink()
    assert "Pairing code: " in moving.out.getvalue()
