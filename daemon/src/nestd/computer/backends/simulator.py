"""iOS Simulator devices (B150): Xcode's `simctl` boots, opens links and takes screenshots;
the device's screen is read and used through Simulator.app's window with the Mac helper."""

import json
import sys
import tempfile
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from nestd.computer.backends.mac import MacBackend
from nestd.computer.images import scale_png
from nestd.computer.models import (
    Action,
    ActResult,
    Availability,
    TargetError,
    TargetInfo,
    TargetKind,
    View,
)
from nestd.gitops.runner import CommandError, CommandRunner

PREFIX = "ios:"
SIMULATOR = "mac:com.apple.iphonesimulator"
XCODE_LINK = "https://apps.apple.com/app/xcode/id497799835"


class SimulatorBackend:
    def __init__(self, mac: MacBackend, run: CommandRunner, cwd: Path) -> None:
        self._mac = mac
        self._run = run
        self._cwd = cwd
        self._booted: set[str] = set()

    @property
    def kind(self) -> TargetKind:
        return "ios"

    async def available(self) -> Availability:
        if sys.platform != "darwin":
            return Availability(kind="ios", ready=False, reason="Only on a Mac.")
        try:
            await self._simctl("help")
        except CommandError:
            return Availability(
                kind="ios", ready=False, reason="Xcode is not installed.", link=XCODE_LINK
            )
        return Availability(kind="ios", ready=True)

    async def targets(self) -> list[TargetInfo]:
        raw = cast(JsonValue, json.loads(await self._simctl("list", "devices", "available", "-j")))
        devices = raw.get("devices") if isinstance(raw, dict) else None
        if not isinstance(devices, dict):
            return []
        return [
            _info(runtime, entry)
            for runtime, entries in devices.items()
            if isinstance(entries, list)
            for entry in (cast(dict[str, JsonValue], e) for e in entries if isinstance(e, dict))
            if isinstance(entry.get("udid"), str)
        ]

    async def open(self, key: str, url: str | None) -> TargetInfo:
        udid = _udid(key)
        info = next((t for t in await self.targets() if t.key == key), None)
        if info is None:
            raise TargetError(f"No simulator {udid}; computer_targets lists them.")
        if not info.running:
            await self._simctl("boot", udid)
            self._booted.add(udid)
        await self._run(["/usr/bin/open", "-g", "-a", "Simulator"], self._cwd)
        await self._simctl("bootstatus", udid, "-b")
        if url:
            await self._simctl("openurl", udid, url)
        return info.model_copy(update={"running": True})

    async def view(self, key: str, window: str | None, screenshot: bool) -> View:
        udid = _udid(key)
        seen = await self._mac.view(SIMULATOR, window or await self._window(key), False)
        image = await self._screenshot(udid) if screenshot else None
        return seen.model_copy(update={"image": image, "note": None})

    async def act(self, key: str, action: Action) -> ActResult:
        udid = _udid(key)
        if action.kind == "navigate":
            await self._simctl("openurl", udid, action.url or "")
            return ActResult(text=f"Opened {action.url} in the simulator.")
        window = action.window or await self._window(key)
        return await self._mac.act(SIMULATOR, action.model_copy(update={"window": window}))

    async def front(self, key: str) -> None:
        _udid(key)
        await self._mac.front(SIMULATOR)

    async def close(self) -> None:
        for udid in sorted(self._booted):
            try:
                await self._simctl("shutdown", udid)
            except CommandError:
                continue
        self._booted.clear()

    async def _window(self, key: str) -> str:
        name = next((t.name for t in await self.targets() if t.key == key), None)
        simulator = await self._mac.targets()
        windows = next((t.windows for t in simulator if t.key == SIMULATOR), ())
        for window_id, title in windows:
            if name and title.startswith(name.split(" (")[0]):
                return window_id
        raise TargetError("The simulator's window is not open; open it with computer_open.")

    async def _screenshot(self, udid: str) -> bytes:
        with tempfile.TemporaryDirectory(prefix="nest-sim-") as folder:
            path = Path(folder) / "shot.png"
            await self._simctl("io", udid, "screenshot", "--type=png", str(path))
            return await scale_png(path.read_bytes())

    async def _simctl(self, *args: str) -> str:
        return await self._run(["/usr/bin/xcrun", "simctl", *args], self._cwd)


def _udid(key: str) -> str:
    if not key.startswith(PREFIX) or len(key) == len(PREFIX):
        raise TargetError(f"{key} is not a simulator target.")
    return key[len(PREFIX) :]


def _info(runtime: str, entry: dict[str, JsonValue]) -> TargetInfo:
    version = runtime.rsplit(".", 1)[-1].replace("iOS-", "iOS ").replace("-", ".")
    return TargetInfo(
        key=f"{PREFIX}{entry['udid']}",
        kind="ios",
        name=f"{entry.get('name', 'Simulator')} ({version})",
        running=entry.get("state") == "Booted",
    )
