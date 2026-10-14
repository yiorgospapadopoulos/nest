import plistlib
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from nestd.paths import AppPaths
from nestd.service.launchd import (
    LABEL,
    LEGACY_LABEL,
    CommandResult,
    LaunchdService,
    ServiceError,
    build_path_env,
    render_plist,
    run_command,
)


class FakeRunner:
    def __init__(self, results: dict[str, CommandResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self._results = results or {}

    def __call__(self, args: Sequence[str]) -> CommandResult:
        self.calls.append(list(args))
        return self._results.get(args[1], CommandResult(0, "", ""))


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")


def make_service(paths: AppPaths, tmp_path: Path, runner: FakeRunner) -> LaunchdService:
    return LaunchdService(
        paths=paths,
        launch_agents_dir=tmp_path / "LaunchAgents",
        uid=501,
        runner=runner,
        program_args=["/venv/bin/python", "-m", "nestd", "serve"],
        path_env="/custom/bin:/usr/bin",
    )


def test_path_env_resolves_user_and_homebrew_tools() -> None:
    entries = build_path_env(Path("/Users/me")).split(":")

    assert entries[:2] == ["/Users/me/.local/bin", "/opt/homebrew/bin"]
    assert {"/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"} <= set(entries)


def test_render_plist(paths: AppPaths) -> None:
    plist: dict[str, Any] = plistlib.loads(
        render_plist(["/venv/bin/python", "-m", "nestd", "serve"], paths, "/a:/b").encode()
    )

    assert plist == {
        "Label": LABEL,
        "ProgramArguments": ["/venv/bin/python", "-m", "nestd", "serve"],
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(paths.logs_dir / "daemon.log"),
        "StandardErrorPath": str(paths.logs_dir / "daemon.log"),
        "EnvironmentVariables": {
            "PATH": "/a:/b",
            "NEST_CONFIG_DIR": str(paths.config_dir),
            "NEST_DATA_DIR": str(paths.data_dir),
        },
    }
    assert LABEL == "com.nest.daemon"


def test_install_writes_plist_and_bootstraps(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner({"bootout": CommandResult(3, "", "No such process")})
    service = make_service(paths, tmp_path, runner)

    service.install()

    assert service.plist_path == tmp_path / "LaunchAgents" / f"{LABEL}.plist"
    written = plistlib.loads(service.plist_path.read_bytes())
    assert written["EnvironmentVariables"]["PATH"] == "/custom/bin:/usr/bin"
    assert paths.logs_dir.is_dir()
    assert runner.calls == [
        ["/bin/launchctl", "bootout", f"gui/501/{LABEL}"],
        ["/bin/launchctl", "bootstrap", "gui/501", str(service.plist_path)],
    ]


def test_install_reports_bootstrap_failure(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner({"bootstrap": CommandResult(5, "", "Input/output error")})
    service = make_service(paths, tmp_path, runner)

    with pytest.raises(ServiceError, match="launchctl bootstrap failed: Input/output error"):
        service.install()


def test_uninstall_boots_out_and_removes_plist(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner()
    service = make_service(paths, tmp_path, runner)
    service.install()
    runner.calls.clear()

    service.uninstall()
    service.uninstall()

    assert not service.plist_path.exists()
    assert runner.calls == [["/bin/launchctl", "bootout", f"gui/501/{LABEL}"]] * 2


def test_remove_legacy_boots_out_the_harness_service_then_removes_its_plist(
    paths: AppPaths, tmp_path: Path
) -> None:
    """B43: the service from before the rename to Nest goes before the new one starts."""
    runner = FakeRunner()
    service = make_service(paths, tmp_path, runner)
    legacy = tmp_path / "LaunchAgents" / "com.harness.daemon.plist"
    legacy.parent.mkdir()
    legacy.write_text("<plist/>", encoding="utf-8")

    assert service.remove_legacy() is True

    assert LEGACY_LABEL == "com.harness.daemon"
    assert runner.calls == [["/bin/launchctl", "bootout", "gui/501/com.harness.daemon"]]
    assert not legacy.exists()
    assert service.remove_legacy() is False
    assert not service.plist_path.exists()


def test_status_reports_installed_and_running(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner({"print": CommandResult(0, "state = running\n", "")})
    service = make_service(paths, tmp_path, runner)
    service.install()

    status = service.status()

    assert status.installed is True
    assert status.loaded is True
    assert status.detail == "state = running\n"
    assert runner.calls[-1] == ["/bin/launchctl", "print", f"gui/501/{LABEL}"]


def test_status_when_not_installed(paths: AppPaths, tmp_path: Path) -> None:
    runner = FakeRunner({"print": CommandResult(113, "", "Could not find service")})

    status = make_service(paths, tmp_path, runner).status()

    assert status.installed is False
    assert status.loaded is False
    assert status.detail == "Could not find service"


def test_run_command_captures_output_and_exit_code() -> None:
    code = "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"

    result = run_command([sys.executable, "-c", code])

    assert result == CommandResult(3, "out\n", "err\n")
