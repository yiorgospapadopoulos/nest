"""B117: the daemon's systemd user service on Linux."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from nestd.paths import AppPaths
from nestd.service.base import CommandResult, ServiceError
from nestd.service.systemd import UNIT_NAME, SystemdService, render_unit

PROGRAM = ["/opt/my venv/bin/python", "-m", "nestd", "serve"]


class FakeRunner:
    def __init__(self, results: dict[str, CommandResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._results = results or {}

    def __call__(self, args: Sequence[str]) -> CommandResult:
        self.calls.append(list(args))
        return self._results.get(args[2], CommandResult(0, "", ""))


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data 100%")


def make_service(paths: AppPaths, tmp_path: Path, runner: FakeRunner) -> SystemdService:
    return SystemdService(
        paths=paths,
        unit_dir=tmp_path / "home" / ".config" / "systemd" / "user",
        runner=runner,
        program_args=PROGRAM,
        path_env="/home/me/.local/bin:/usr/bin",
    )


def test_the_unit_restarts_the_daemon_with_its_folders_and_log(paths: AppPaths) -> None:
    """Restart=always is what brings the daemon back after the restart route's SIGTERM.
    Spaces, quotes and `%` in values are escaped, so systemd reads back the same values."""
    unit = render_unit(PROGRAM, paths, "/home/me/.local/bin:/usr/bin")
    log = str(paths.logs_dir / "daemon.log").replace("%", "%%")

    assert unit.splitlines() == [
        "[Unit]",
        "Description=Nest daemon",
        "",
        "[Service]",
        'ExecStart="/opt/my venv/bin/python" "-m" "nestd" "serve"',
        "Restart=always",
        "RestartSec=5",
        "KillMode=process",
        'Environment="PATH=/home/me/.local/bin:/usr/bin"',
        f'Environment="NEST_CONFIG_DIR={paths.config_dir}"',
        f'Environment="NEST_DATA_DIR={str(paths.data_dir).replace("%", "%%")}"',
        f"StandardOutput=append:{log}",
        f"StandardError=append:{log}",
        "",
        "[Install]",
        "WantedBy=default.target",
    ]
    assert UNIT_NAME == "nest.service"


def test_values_that_systemd_would_expand_or_split_are_escaped(paths: AppPaths) -> None:
    unit = render_unit(['/bin/a"b\\c', "$HOME"], paths, "/x")

    assert 'ExecStart="/bin/a\\"b\\\\c" "$$HOME"' in unit.splitlines()


def test_a_value_with_a_line_break_is_refused(paths: AppPaths) -> None:
    """A line break would start a new unit setting."""
    with pytest.raises(ServiceError, match="line break"):
        render_unit(["/bin/python", "x\nExecStartPre=/bin/evil"], paths, "/x")


def test_install_writes_the_unit_reloads_enables_and_restarts(
    paths: AppPaths, tmp_path: Path
) -> None:
    runner = FakeRunner()
    service = make_service(paths, tmp_path, runner)

    service.install()

    assert service.unit_path == tmp_path / "home" / ".config" / "systemd" / "user" / UNIT_NAME
    assert "Restart=always" in service.unit_path.read_text(encoding="utf-8")
    assert paths.logs_dir.is_dir()
    assert runner.calls == [
        ["systemctl", "--user", "daemon-reload"],
        ["systemctl", "--user", "enable", UNIT_NAME],
        ["systemctl", "--user", "restart", UNIT_NAME],
    ]


def test_install_reports_a_failed_systemctl(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner(
        {"daemon-reload": CommandResult(1, "", "Failed to connect to bus: No medium found\n")}
    )

    with pytest.raises(
        ServiceError, match="systemctl --user daemon-reload failed: Failed to connect to bus"
    ):
        make_service(paths, tmp_path, runner).install()
    assert runner.calls == [["systemctl", "--user", "daemon-reload"]]


def test_uninstall_disables_removes_the_unit_and_reloads(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner({"disable": CommandResult(1, "", "Unit nest.service not loaded")})
    service = make_service(paths, tmp_path, runner)
    service.install()
    runner.calls.clear()

    service.uninstall()

    assert not service.unit_path.exists()
    assert runner.calls == [
        ["systemctl", "--user", "disable", "--now", UNIT_NAME],
        ["systemctl", "--user", "daemon-reload"],
    ]


def test_status_reports_installed_and_running(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner({"status": CommandResult(0, "Active: active (running)\n", "")})
    service = make_service(paths, tmp_path, runner)
    service.install()

    status = service.status()

    assert (status.installed, status.loaded) == (True, True)
    assert status.detail == "Active: active (running)\n"
    assert runner.calls[-1] == ["systemctl", "--user", "status", "--no-pager", UNIT_NAME]


def test_status_when_not_installed(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner({"status": CommandResult(4, "", "Unit nest.service could not be found.")})

    status = make_service(paths, tmp_path, runner).status()

    assert (status.installed, status.loaded) == (False, False)
    assert status.detail == "Unit nest.service could not be found."


def test_there_is_no_service_from_before_the_rename(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner()

    assert make_service(paths, tmp_path, runner).remove_legacy() is False
    assert runner.calls == []
