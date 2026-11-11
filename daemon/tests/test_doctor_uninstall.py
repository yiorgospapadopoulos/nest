"""`nest uninstall` removes Nest and, unless asked, nothing of the user's."""

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest

from nestd.doctor.machine import Machine
from nestd.doctor.uninstall import NotAReleaseError, Uninstall
from nestd.paths import AppPaths
from nestd.platform import LINUX, MACOS
from nestd.service.base import CommandResult, ServiceStatus


class Service:
    unit_path = Path("/nowhere")

    def __init__(self) -> None:
        self.removed = False

    def install(self) -> None: ...

    def remove_legacy(self) -> bool:
        return False

    def stop(self) -> None: ...

    def uninstall(self) -> None:
        self.removed = True

    def status(self) -> ServiceStatus:
        return ServiceStatus(installed=True, loaded=True, detail="")


def _run(_args: object, _env: object, _limit: float = 1.0) -> CommandResult:
    return CommandResult(0, "", "")


@pytest.fixture
def machine(tmp_path: Path) -> Machine:
    home = tmp_path / "home"
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    for folder in (
        paths.daemon_dir / "1.0.0",
        paths.bin_dir,
        paths.environments_dir,
        paths.engines_dir,
        paths.data_dir / "app",
        paths.attachments_dir,
        paths.config_dir,
        home / ".local" / "bin",
        home / ".local" / "share" / "applications",
        home / ".local" / "share" / "icons" / "hicolor" / "32x32" / "apps",
    ):
        folder.mkdir(parents=True)
    paths.db_path.write_text("chats", encoding="utf-8")
    paths.settings_file.write_text("[server]\n", encoding="utf-8")
    (home / ".local" / "bin" / "nest").symlink_to(paths.daemon_dir / "current" / "bin" / "nest")
    (home / ".local" / "share" / "applications" / "nest.desktop").touch()
    icon = home / ".local" / "share" / "icons" / "hicolor" / "32x32" / "apps" / "nest-desktop.png"
    icon.touch()

    def no_secret() -> None:
        return None

    def up(_port: int) -> bool:
        return True

    return Machine(
        paths=paths,
        platform=LINUX,
        home=home,
        env={"PATH": "", "NEST_MAC_APP": str(tmp_path / "Nest.app")},
        port=8765,
        service=Service(),
        read_secret=no_secret,
        packaged=True,
        run=_run,
        healthy=up,
    )


def test_it_removes_nest_and_keeps_the_users_things(machine: Machine) -> None:
    said: list[str] = []
    paths = machine.paths

    Uninstall(machine, said.append).run(delete_data=False)

    assert isinstance(machine.service, Service)
    assert machine.service.removed
    for gone in (
        paths.daemon_dir,
        paths.bin_dir,
        paths.environments_dir,
        paths.engines_dir,
        paths.data_dir / "app",
        machine.home / ".local" / "bin" / "nest",
        machine.home / ".local" / "share" / "applications" / "nest.desktop",
    ):
        assert not gone.exists(), gone
        assert not gone.is_symlink(), gone
    assert paths.db_path.read_text(encoding="utf-8") == "chats"
    assert paths.settings_file.exists()
    assert paths.attachments_dir.exists()
    assert any("Kept your chats" in line for line in said)
    # B166: the command that ends Nest's share only, never one that ends every share.
    assert any("tailscale serve --https=443 off" in line for line in said)
    assert not any("serve reset" in line for line in said)


def test_delete_data_is_the_only_way_chats_go(machine: Machine) -> None:
    said: list[str] = []

    Uninstall(machine, said.append).run(delete_data=True)

    assert not machine.paths.data_dir.exists()
    assert not machine.paths.config_dir.exists()


@pytest.mark.parametrize(
    ("answers", "gone"),
    [
        # Each service empties: one item deleted, then "not found".
        ([0, 44, 44], True),
        # A locked Keychain is not "they all went".
        ([51], False),
        ([0, 44, 51], False),
    ],
)
def test_secrets_only_count_as_deleted_when_the_keychain_says_so(
    machine: Machine, answers: list[int], gone: bool
) -> None:
    left = iter(answers)
    services: list[str] = []

    def keychain(args: Sequence[str], _env: object, _limit: float = 1.0) -> CommandResult:
        if args[0] == "security":
            services.append(args[-1])
            return CommandResult(next(left, 44), "", "")
        return CommandResult(0, "", "")

    said: list[str] = []
    mac = replace(machine, platform=MACOS, run=keychain)

    Uninstall(mac, said.append).run(delete_data=True)

    assert any("Deleted your secrets" in line for line in said) is gone
    if gone:
        assert services == ["nest", "nest", "harness"]


def test_a_checkout_is_refused_and_untouched(machine: Machine) -> None:
    checkout = replace(machine, packaged=False)

    with pytest.raises(NotAReleaseError):
        Uninstall(checkout, print).run(delete_data=True)

    assert machine.paths.db_path.exists()
    assert machine.paths.daemon_dir.exists()
