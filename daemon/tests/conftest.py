from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.sessions.checkpoints import FileCheckpoints
from nestd.storage.db import Database
from tests.db_support import migrated_copy
from tests.fakes import FakeClock, FakeSecretStore

# The configuration API tests' daemon and engine folders (B97); a module's own fixture of
# the same name wins.
pytest_plugins = ("tests.configuration_api",)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "loops: the test's API runs the services that poll on a timer (B111)"
    )


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = await Database.open(await migrated_copy(tmp_path / "nest.db"))
    yield database
    await database.close()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def secrets() -> FakeSecretStore:
    return FakeSecretStore()


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the user's git config and identity out of tests that run real git."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for role in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{role}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{role}_EMAIL", "test@example.com")


@pytest.fixture
def engine_checkpoints_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chats keep no git snapshots, as in a folder without git: files are restored by the
    engine's own checkpoints, which only Claude Code keeps (B145).
    """

    async def no_snapshot(*_: object) -> None:
        return None

    monkeypatch.setattr(FileCheckpoints, "take", no_snapshot)
