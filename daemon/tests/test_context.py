from pathlib import Path

import pytest

from nestd.config.models import Settings
from nestd.context import AppContext
from nestd.local.memory import memory_warning
from nestd.paths import AppPaths
from nestd.platform import LINUX
from tests.fakes import FakeClock, FakeSecretStore


async def test_build_prepares_directories_settings_and_services(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")

    async def machine() -> str:
        return "Studio"

    ctx = await AppContext.build(paths, secrets, clock, machine=machine)
    try:
        event = await ctx.bus.publish("x", {})
        devices = await ctx.devices.list_devices()
    finally:
        await ctx.close()

    assert ctx.paths == paths
    assert ctx.clock is clock
    assert ctx.machine == "Studio"
    assert ctx.settings == Settings()
    assert paths.settings_file.is_file()
    assert paths.db_path.is_file()
    assert paths.logs_dir.is_dir()
    assert event.ts == clock.current
    # Building has no side effects beyond files: no devices, no secrets, no modules.
    assert devices == []
    assert secrets.values == {}
    assert ctx.modules.started == []


async def test_close_closes_the_database(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    ctx = await AppContext.build(paths, secrets, clock)

    await ctx.close()

    with pytest.raises(ValueError, match="no active connection"):
        await ctx.db.fetch_all("SELECT 1")


async def test_on_linux_the_daemons_machine_is_this_computer(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    """B117: text about the machine the daemon runs on names no Mac there."""
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    ctx = await AppContext.build(paths, secrets, clock, platform=LINUX)
    try:
        await ctx.devices.ensure_local_device()
        devices = await ctx.devices.list_devices()
    finally:
        await ctx.close()

    assert [device.name for device in devices] == ["This computer"]
    assert memory_warning(20 * 2**30, 24 * 2**30, LINUX.machine_noun) == (
        "Needs about 20 GB of this computer's 24 GB: other work may slow down or the"
        " computer may stall."
    )
