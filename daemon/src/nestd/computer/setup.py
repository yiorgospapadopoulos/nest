"""The computer-use service of the running daemon, with the backends this computer has
(B150): Mac apps and simulators only on a Mac."""

import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from nestd.computer.backends.android import AndroidBackend
from nestd.computer.backends.base import Backend
from nestd.computer.backends.browser import BrowserBackend
from nestd.computer.backends.mac import MacBackend
from nestd.computer.backends.simulator import SimulatorBackend
from nestd.computer.helper import Helper, HelperError, helper_app, socket_path
from nestd.computer.service import (
    Ask,
    ComputerService,
    Interrupt,
    PermissionName,
)
from nestd.config.models import ComputerUseSettings
from nestd.events.bus import EventBus
from nestd.gitops.runner import run_command
from nestd.sessions.store import SessionStore


class HelperPermissions:
    def __init__(self, helper: Helper) -> None:
        self._helper = helper

    async def granted(self) -> tuple[bool, bool] | None:
        if not self._helper.installed:
            return None
        try:
            hello = await self._helper.call("hello")
        except HelperError:
            return None
        return hello.get("accessibility") is True, hello.get("screen_recording") is True

    async def ask(self, name: PermissionName) -> bool:
        answer = await self._helper.call("ask_permission", {"name": name})
        return answer.get("granted") is True


def computer_service(
    *,
    data_dir: Path,
    env: Mapping[str, str],
    settings: Callable[[], ComputerUseSettings],
    store: SessionStore,
    bus: EventBus,
    ask: Ask,
    interrupt: Interrupt,
    backends: Sequence[Backend] | None = None,
) -> ComputerService:
    """`backends` replaces the computer's own, as in tests."""
    permissions: HelperPermissions | None = None
    if backends is None:
        found: list[Backend] = []
        if sys.platform == "darwin":
            helper = Helper(helper_app(env), socket_path(data_dir))
            mac = MacBackend(helper)
            found += [mac, SimulatorBackend(mac, run_command, data_dir)]
            permissions = HelperPermissions(helper)
        profile = data_dir / "computer" / "browser"
        found += [AndroidBackend(env=env), BrowserBackend(profile=profile, env=env)]
        backends = found
    return ComputerService(
        backends,
        settings=settings,
        store=store,
        bus=bus,
        ask=ask,
        interrupt=interrupt,
        permissions=permissions,
    )
