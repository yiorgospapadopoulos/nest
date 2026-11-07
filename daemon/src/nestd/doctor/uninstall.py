"""`nest uninstall`: everything an install put on the machine, and by default nothing the
user made. Chats, config and secrets stay unless asked, and it says what stayed.
"""

import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nestd.auth.secrets import LEGACY_SERVICE_NAME, SERVICE_NAME
from nestd.doctor.machine import Machine
from nestd.platform.linux import xdg_dir

_SECRET_LOOP_LIMIT = 100
_KEYCHAIN_ITEM_NOT_FOUND = 44
_TAILSCALE_NOTE = "If you shared Nest with Tailscale, stop that with: tailscale serve reset"


class NotAReleaseError(Exception):
    """A checkout's Nest is the developer's own, and is removed by hand."""


def app_paths(machine: Machine) -> tuple[Path, ...]:
    """What the install script put outside Nest's own folders."""
    home = machine.home
    command = home / ".local" / "bin" / "nest"
    if machine.platform.name == "macos":
        return (Path(machine.env.get("NEST_MAC_APP", "/Applications/Nest.app")), command)
    share = xdg_dir(machine.env, "XDG_DATA_HOME", home / ".local" / "share")
    icons = share / "icons" / "hicolor"
    return (
        machine.paths.data_dir / "app",
        share / "applications" / "nest.desktop",
        *sorted(icons.glob("*/apps/nest-desktop.png")),
        command,
    )


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def _delete_keychain_items(machine: Machine, service: str) -> bool:
    """Deletes until the Keychain says none is left. Any other answer, such as a locked
    Keychain, is a failure, so nobody is told their secrets went when they did not.
    """
    for _ in range(_SECRET_LOOP_LIMIT):
        code = machine.command("security", "delete-generic-password", "-s", service).returncode
        if code == _KEYCHAIN_ITEM_NOT_FOUND:
            return True
        if code != 0:
            return False
    return False


def _delete_secrets(machine: Machine) -> bool:
    """Whether every secret went, under the old service name as well."""
    services = (SERVICE_NAME, LEGACY_SERVICE_NAME)
    if machine.platform.name == "macos":
        results = [_delete_keychain_items(machine, service) for service in services]
        return all(results)
    program = machine.which("secret-tool")
    if program is None:
        return False
    codes = [machine.command(program, "clear", "service", name).returncode for name in services]
    return not any(codes)


def _quit_app(machine: Machine) -> None:
    if machine.platform.name == "macos":
        machine.command("osascript", "-e", 'quit app "Nest"')
    else:
        machine.command("pkill", "-x", "nest-desktop")


@dataclass(frozen=True)
class Uninstall:
    machine: Machine
    out: Callable[[str], None]

    def run(self, *, delete_data: bool) -> None:
        machine = self.machine
        if not machine.packaged:
            msg = "This Nest runs from a checkout. Remove it with `nestd service uninstall`."
            raise NotAReleaseError(msg)
        paths = machine.paths
        _quit_app(machine)
        machine.service.uninstall()
        self.out("Removed the background service")
        for path in app_paths(machine):
            _remove(path)
        self.out("Removed the app and the nest command")
        for folder in (paths.environments_dir, paths.engines_dir, paths.bin_dir, paths.daemon_dir):
            _remove(folder)
        self.out("Removed Nest's programs")
        if delete_data:
            self._delete_data()
        else:
            self.out(f"Kept your chats and data in {paths.data_dir}")
            self.out(f"Kept your settings in {paths.config_dir}")
            self.out("Kept your secrets in the system's store")
            self.out("Installing again brings it all back. To delete it, remove those two folders.")
        self.out(_TAILSCALE_NOTE)

    def _delete_data(self) -> None:
        paths = self.machine.paths
        _remove(paths.data_dir)
        _remove(paths.config_dir)
        self.out("Deleted your chats, data and settings")
        if _delete_secrets(self.machine):
            self.out("Deleted your secrets from the system's store")
        else:
            self.out(
                "Could not delete your secrets. They're under `nest` and `harness` "
                "in the system's store."
            )
