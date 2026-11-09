"""iOS Simulator devices (B150): the list `simctl` gives, and booting only what is off."""

import json
from collections.abc import Sequence
from pathlib import Path

from nestd.computer.backends.mac import MacBackend
from nestd.computer.backends.simulator import SimulatorBackend
from nestd.computer.helper import Helper

DEVICES = {
    "devices": {
        "com.apple.CoreSimulator.SimRuntime.iOS-27-0": [
            {"udid": "A1", "name": "iPhone 18 Pro", "state": "Booted"},
            {"udid": "B2", "name": "iPhone 17e", "state": "Shutdown"},
        ],
        "com.apple.CoreSimulator.SimRuntime.watchOS-13-0": "not a list",
    }
}


class Simctl:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []

    async def __call__(self, argv: Sequence[str], _cwd: Path) -> str:
        self.calls.append(tuple(argv))
        return json.dumps(DEVICES) if "list" in argv else ""


def backend(tmp_path: Path, run: Simctl) -> SimulatorBackend:
    mac = MacBackend(Helper(tmp_path / "none.app", tmp_path / "s.sock"))
    return SimulatorBackend(mac, run, tmp_path)


async def test_devices_are_listed_with_their_runtime(tmp_path: Path) -> None:
    targets = await backend(tmp_path, Simctl()).targets()

    assert [(t.key, t.name, t.running) for t in targets] == [
        ("ios:A1", "iPhone 18 Pro (iOS 27.0)", True),
        ("ios:B2", "iPhone 17e (iOS 27.0)", False),
    ]


async def test_open_boots_only_a_device_that_is_off_and_close_shuts_only_it(
    tmp_path: Path,
) -> None:
    run = Simctl()
    simulators = backend(tmp_path, run)

    await simulators.open("ios:A1", None)
    await simulators.open("ios:B2", "https://example.com")
    await simulators.close()

    simctl = [c[2:] for c in run.calls if c[:2] == ("/usr/bin/xcrun", "simctl") and "list" not in c]
    assert ("boot", "A1") not in simctl
    assert ("boot", "B2") in simctl
    assert ("openurl", "B2", "https://example.com") in simctl
    assert [c for c in simctl if c[0] == "shutdown"] == [("shutdown", "B2")]
