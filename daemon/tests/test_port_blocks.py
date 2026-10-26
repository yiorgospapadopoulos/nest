"""Port blocks per folder (B108)."""

import logging

import pytest

from nestd.config.models import PortSettings
from nestd.runs.blocks import PortBlock, PortBlocks
from nestd.storage.db import Database
from tests.fakes import FakeClock


class Settings:
    def __init__(self, ports: PortSettings) -> None:
        self.ports = ports

    def __call__(self) -> PortSettings:
        return self.ports


@pytest.fixture
def settings() -> Settings:
    return Settings(PortSettings(start=50000, size=10, blocks=3))


@pytest.fixture
def blocks(db: Database, clock: FakeClock, settings: Settings) -> PortBlocks:
    return PortBlocks(db, clock, settings)


async def test_each_folder_gets_the_lowest_free_block_and_keeps_it(blocks: PortBlocks) -> None:
    first = await blocks.block_for("/a", "web")
    second = await blocks.block_for("/b", "web")
    again = await blocks.block_for("/a", "web")

    assert first == PortBlock(start=50000, size=10)
    assert second == PortBlock(start=50010, size=10)
    assert again == first


async def test_a_freed_block_is_given_to_the_next_folder(blocks: PortBlocks) -> None:
    await blocks.block_for("/a", "web")
    await blocks.block_for("/b", "web")
    await blocks.free("/a")

    assert await blocks.block_for("/c", "api") == PortBlock(start=50000, size=10)
    assert await blocks.block_for("/a", "web") == PortBlock(start=50020, size=10)


async def test_without_a_free_block_a_folder_gets_none_and_a_warning(
    blocks: PortBlocks, caplog: pytest.LogCaptureFixture
) -> None:
    for folder in ("/a", "/b", "/c"):
        await blocks.block_for(folder, "web")

    with caplog.at_level(logging.WARNING):
        none = await blocks.block_for("/d", "web")

    assert none is None
    assert "no free port block for /d" in caplog.text
    assert await blocks.folders("web") == ["/a", "/b", "/c"]


async def test_a_block_that_no_longer_fits_the_settings_is_given_again(
    blocks: PortBlocks, settings: Settings
) -> None:
    for folder in ("/a", "/b", "/c"):
        await blocks.block_for(folder, "web")
    await blocks.free("/a")
    settings.ports = PortSettings(start=60000, size=4, blocks=2)

    kept = await blocks.block_for("/b", "web")
    moved = await blocks.block_for("/c", "web")

    # /b keeps index 1 at the new start and size; /c had index 2, past the last block.
    assert kept == PortBlock(start=60004, size=4)
    assert moved == PortBlock(start=60000, size=4)


async def test_a_repo_lists_and_frees_its_own_folders(blocks: PortBlocks) -> None:
    await blocks.block_for("/web/b", "web")
    await blocks.block_for("/api", "api")
    await blocks.block_for("/web/a", "web")

    listed = await blocks.folders("web")
    await blocks.free_repo("web")

    assert listed == ["/web/a", "/web/b"]
    assert await blocks.folders("web") == []
    assert await blocks.folders("api") == ["/api"]


def test_a_blocks_env_names_each_port() -> None:
    assert PortBlock(start=41020, size=3).env() == {
        "NEST_PORT": "41020",
        "NEST_PORT_1": "41021",
        "NEST_PORT_2": "41022",
    }
    assert PortBlock(start=41020, size=1).env() == {"NEST_PORT": "41020"}
