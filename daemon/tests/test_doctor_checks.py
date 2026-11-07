"""What the setup guide and `nest doctor` would get wrong in ways that hurt: opening Apple's
install dialog by itself, sending someone to the wrong fix, or hanging on a locked keyring.
"""

import os
import sqlite3
import stat
import time
from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from nestd.doctor.checks import (
    by_rank,
    check_engine,
    check_git,
    check_github,
    check_secret_service,
    check_service,
    check_tailscale,
    run_checks,
    share_on_tailnet,
)
from nestd.doctor.machine import Machine, json_object, run_limited, within_limit
from nestd.paths import AppPaths
from nestd.platform import LINUX, MACOS
from nestd.service.base import CommandResult, ServiceStatus


class FakeService:
    def __init__(self, status: ServiceStatus) -> None:
        self._status = status
        self.unit_path = Path("/nowhere")

    def install(self) -> None: ...

    def remove_legacy(self) -> bool:
        return False

    def stop(self) -> None: ...

    def uninstall(self) -> None: ...

    def status(self) -> ServiceStatus:
        return self._status


class Commands:
    """Answers by the command's first words; every command run is kept."""

    def __init__(self, answers: Mapping[str, CommandResult] | None = None) -> None:
        self.answers = answers or {}
        self.ran: list[str] = []

    def __call__(
        self, args: Sequence[str], env: Mapping[str, str], limit: float = 10.0
    ) -> CommandResult:
        line = " ".join(Path(args[0]).name if i == 0 else a for i, a in enumerate(args))
        self.ran.append(line)
        for start, result in self.answers.items():
            if line.startswith(start):
                return result
        return CommandResult(1, "", "")


def _program(folder: Path, name: str) -> None:
    path = folder / name
    path.write_text("#!/bin/sh\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def _machine(
    tmp_path: Path, commands: Commands, *, programs: Sequence[str] = (), mac: bool = True
) -> Machine:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (tmp_path / "home").mkdir(exist_ok=True)
    for name in programs:
        _program(bin_dir, name)
    paths = AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        codex_home=tmp_path / "codex",
    )
    return Machine(
        paths=paths,
        platform=MACOS if mac else LINUX,
        home=tmp_path / "home",
        env={"PATH": str(bin_dir)},
        port=8765,
        service=FakeService(ServiceStatus(installed=True, loaded=True, detail="")),
        read_secret=lambda: None,
        packaged=True,
        run=commands,
        healthy=lambda _: True,
    )


def test_an_engine_from_more_engines_counts(tmp_path: Path) -> None:
    machine = _machine(tmp_path, Commands())
    machine.paths.data_dir.mkdir(parents=True)
    database = sqlite3.connect(machine.paths.db_path)
    database.execute("CREATE TABLE engine_accounts (provider TEXT, signed_in INTEGER)")
    database.execute("INSERT INTO engine_accounts VALUES ('claude', 0), ('opencode', 1)")
    database.commit()
    database.close()

    check = check_engine(machine)

    assert (check.state, check.detail) == ("ok", "Another engine")


def test_apples_git_stub_is_never_run(tmp_path: Path) -> None:
    """Running it opens an install dialog, so the check may only look."""

    class CleanMac(Machine):
        def which(self, program: str) -> str | None:
            return f"/usr/bin/{program}"

    commands = Commands({"xcode-select -p": CommandResult(2, "", "no developer tools")})

    check = check_git(CleanMac(**vars(_machine(tmp_path, commands))))

    assert check.state == "missing"
    assert check.fix is not None
    assert check.fix.value == "xcode-select --install"
    assert not [line for line in commands.ran if line.startswith("git")]


@pytest.mark.parametrize(
    ("programs", "line"),
    [(["brew"], "brew install gh"), ([], "Homebrew/install/HEAD/install.sh")],
)
def test_a_mac_gets_homebrews_line_for_gh(tmp_path: Path, programs: list[str], line: str) -> None:
    class OnlyThese(Machine):
        """Sees only the stand-ins, never this computer's own brew or gh."""

        def which(self, program: str) -> str | None:
            return f"/opt/homebrew/bin/{program}" if program in programs else None

    check = check_github(OnlyThese(**vars(_machine(tmp_path, Commands()))))

    assert check.fix is not None
    assert check.fix.kind == "command"
    assert line in check.fix.value


def test_a_real_git_answers_with_its_version(tmp_path: Path) -> None:
    commands = Commands({"git --version": CommandResult(0, "git version 2.43.0\n", "")})

    check = check_git(_machine(tmp_path, commands, programs=["git"], mac=False))

    assert (check.state, check.detail) == ("ok", "2.43.0")


def test_an_engine_is_a_login_or_local_models(tmp_path: Path) -> None:
    commands = Commands({"claude auth status": CommandResult(0, '{"loggedIn": false}', "")})
    machine = _machine(tmp_path, commands, programs=["claude"])

    assert check_engine(machine).state == "missing"

    commands.answers = {"claude auth status": CommandResult(0, '{"loggedIn": true}', "")}
    assert (check_engine(machine).state, check_engine(machine).detail) == ("ok", "Claude Code")


def test_a_packaged_install_gets_the_one_line_repair(tmp_path: Path) -> None:
    commands = Commands()
    machine = replace(
        _machine(tmp_path, commands),
        service=FakeService(ServiceStatus(installed=False, loaded=False, detail="")),
        env={"PATH": "", "NEST_RELEASE_URL": "http://127.0.0.1:41050"},
    )

    check = check_service(machine)

    assert check.state == "missing"
    assert check.fix is not None
    # A piped script cannot tell where it came from, so the address goes with it.
    address = "http://127.0.0.1:41050"
    assert check.fix.value == f"curl -fsSL {address}/install.sh | NEST_RELEASE_URL={address} sh"


def test_an_install_keeps_following_the_address_it_came_from(tmp_path: Path) -> None:
    """Regression: the daemon-down line always named GitHub, so a test install's 404'd."""
    machine = replace(
        _machine(tmp_path, Commands()),
        service=FakeService(ServiceStatus(installed=False, loaded=False, detail="")),
    )
    machine.paths.data_dir.mkdir(parents=True)
    (machine.paths.data_dir / "release-url").write_text("http://10.0.0.2:41051\n")

    check = check_service(machine)

    assert check.fix is not None
    assert "http://10.0.0.2:41051/install.sh" in check.fix.value


def test_tailscale_walks_from_install_to_a_paired_phone(tmp_path: Path) -> None:
    running = '{"BackendState": "Running", "Self": {"DNSName": "air.tail3f.ts.net."}}'
    commands = Commands({"tailscale status": CommandResult(0, running, "")})
    machine = _machine(tmp_path, commands, programs=["tailscale"], mac=False)

    check = check_tailscale(machine)
    # Sharing is a button now, so no command; and no pairing code before it is shared.
    assert (check.stage, check.fix, check.detail) == ("share", None, "air.tail3f.ts.net")

    commands.answers = {
        "tailscale status": CommandResult(0, running, ""),
        "tailscale serve": CommandResult(0, '{"proxy": "http://127.0.0.1:8765"}', ""),
    }
    check = check_tailscale(machine)
    assert (check.state, check.stage) == ("missing", "pair")


def test_sharing_brings_back_tailscales_link_to_turn_https_on(tmp_path: Path) -> None:
    running = '{"BackendState": "Running", "Self": {"DNSName": "air.tail3f.ts.net."}}'
    waiting = "Serve is not enabled on your tailnet.\nTo enable, visit:\n\n  https://login.tailscale.com/f/serve?node=n1\n"
    commands = Commands(
        {
            "tailscale status": CommandResult(0, running, ""),
            "tailscale serve --bg": CommandResult(124, waiting, "timed out"),
        }
    )

    check = share_on_tailnet(_machine(tmp_path, commands, programs=["tailscale"], mac=False))

    assert "tailscale serve --bg 8765" in commands.ran
    assert check.fix is not None
    assert check.fix.value == "https://login.tailscale.com/f/serve?node=n1"


def test_sharing_never_takes_the_address_from_another_app(tmp_path: Path) -> None:
    """Regression: a test copy's Share took the tailnet address from the user's own Nest."""
    running = '{"BackendState": "Running", "Self": {"DNSName": "air.tail3f.ts.net."}}'
    shared = '{"Web": {"air.tail3f.ts.net:443": {"Handlers": {"/": {"Proxy": "http://127.0.0.1:8765"}}}}}'
    commands = Commands(
        {
            "tailscale status": CommandResult(0, running, ""),
            "tailscale serve status": CommandResult(0, shared, ""),
        }
    )
    machine = replace(_machine(tmp_path, commands, programs=["tailscale"], mac=False), port=41053)

    check = share_on_tailnet(machine)

    assert not [line for line in commands.ran if line.startswith("tailscale serve --bg")]
    assert "port 8765" in check.message


def test_check_nest_puts_what_stops_nest_first_and_what_is_fine_last(tmp_path: Path) -> None:
    machine = replace(
        _machine(tmp_path, Commands(), mac=False),
        service=FakeService(ServiceStatus(installed=False, loaded=False, detail="")),
    )

    ranked = by_rank(run_checks(machine))

    ranks = [check.rank for check in ranked]
    assert ranks == sorted(ranks)
    assert ranked[0].importance == "required"
    assert ranked[0].state == "missing"


@pytest.mark.parametrize(("mac", "absent"), [(True, "secret_service"), (False, "dictation")])
def test_a_check_for_the_other_platform_is_left_out(tmp_path: Path, mac: bool, absent: str) -> None:
    ids = {check.id for check in run_checks(_machine(tmp_path, Commands(), mac=mac))}

    assert absent not in ids


def test_a_locked_keyring_cannot_hang_the_check(tmp_path: Path) -> None:
    def stuck() -> None:
        time.sleep(30)

    started = time.monotonic()
    failure = within_limit(stuck, limit=0.05)

    assert failure == "it did not answer in time"
    assert time.monotonic() - started < 5


def test_a_missing_secret_service_says_what_to_install(tmp_path: Path) -> None:
    def missing() -> None:
        raise RuntimeError("no store")

    machine = replace(_machine(tmp_path, Commands(), mac=False), read_secret=missing)

    check = check_secret_service(machine)

    assert check.state == "missing"
    assert "gnome-keyring" in check.message


def test_every_check_answers_with_nothing_installed_and_the_daemon_down(tmp_path: Path) -> None:
    def down(_port: int) -> bool:
        return False

    machine = replace(
        _machine(tmp_path, Commands(), mac=False),
        service=FakeService(ServiceStatus(installed=False, loaded=False, detail="")),
        healthy=down,
    )

    checks = run_checks(machine)

    assert len({check.id for check in checks}) == len(checks)
    assert next(check for check in checks if check.id == "service").state == "missing"


def test_a_command_that_hangs_is_ended_and_a_missing_one_is_no_crash() -> None:
    assert run_limited(["/bin/sleep", "30"], {}, 0.05).returncode == 124
    assert run_limited(["/no/such/program"], {}, 1.0).returncode == 127


@pytest.mark.parametrize("text", ["", "[]", "{not json"])
def test_json_object_refuses_what_is_not_an_object(text: str) -> None:
    assert json_object(text) is None


def test_the_service_path_is_searched_first(tmp_path: Path) -> None:
    machine = _machine(tmp_path, Commands())

    parts = machine.search_env["PATH"].split(os.pathsep)

    assert parts[-1] == str(tmp_path / "bin")
