import json
import tomllib
from pathlib import Path

import pytest

from nestd.config.errors import ConfigError
from nestd.config.loader import load_project_order, load_settings, save_project_order, save_repo
from nestd.config.models import RepoConfig
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.paths import AppPaths
from nestd.repos.service import RepoService
from nestd.storage.db import Database
from tests.fakes import FakeClock


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def add_repos(paths: AppPaths, tmp_path: Path, *names: str) -> None:
    for name in names:
        save_repo(paths, RepoConfig(name=name, path=tmp_path / name, git=False))


def names(repos: list[RepoConfig]) -> list[str]:
    return [repo.name for repo in repos]


async def reordered_events(db: Database) -> list[object]:
    rows = await db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.REPOS_REORDERED,)
    )
    return [(row["session_id"], json.loads(row["payload"])) for row in rows]


def test_reading_the_order_does_not_create_the_settings_file(paths: AppPaths) -> None:
    assert load_project_order(paths) == []
    assert not paths.settings_file.exists()


def test_the_order_defaults_to_empty_in_a_settings_file(paths: AppPaths) -> None:
    paths.settings_file.write_text("[usage]\nrefresh_minutes = 3\n", encoding="utf-8")

    assert load_project_order(paths) == []
    assert load_settings(paths).projects.order == []


def test_saving_the_order_keeps_the_other_sections(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[agents]\nmodel = "opus"\n[usage]\nrefresh_minutes = 5\n', encoding="utf-8"
    )

    saved = save_project_order(paths, ["b", "a"])

    assert saved == ["b", "a"]
    assert load_project_order(paths) == ["b", "a"]
    data = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert data == {
        "agents": {"model": "opus"},
        "usage": {"refresh_minutes": 5},
        "projects": {"order": ["b", "a"]},
    }


def test_a_broken_settings_file_is_reported_and_kept(paths: AppPaths) -> None:
    paths.settings_file.write_text("[projects\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid TOML"):
        load_project_order(paths)
    with pytest.raises(ConfigError, match="invalid TOML"):
        save_project_order(paths, ["a"])

    assert paths.settings_file.read_text(encoding="utf-8") == "[projects\n"


def test_repos_are_listed_in_the_saved_order_then_by_file_name(
    paths: AppPaths, tmp_path: Path
) -> None:
    add_repos(paths, tmp_path, "alpha", "beta", "gamma", "delta")
    service = RepoService(paths)

    assert names(service.list_repos()) == ["alpha", "beta", "delta", "gamma"]

    # A name that is no longer a repo is ignored; repos left out follow in file order.
    save_project_order(paths, ["gamma", "gone", "beta"])

    assert names(service.list_repos()) == ["gamma", "beta", "alpha", "delta"]
    assert service.get("delta").name == "delta"


async def test_reorder_saves_known_names_then_the_rest_and_announces(
    paths: AppPaths, tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    add_repos(paths, tmp_path, "alpha", "beta", "gamma", "delta")
    save_project_order(paths, ["delta"])
    service = RepoService(paths, bus=EventBus(db, clock))

    repos = await service.reorder(["gamma", "unknown", "alpha", "gamma"])

    # Duplicates keep their first place; the rest keep their current order after.
    expected = ["gamma", "alpha", "delta", "beta"]
    assert names(repos) == expected
    assert load_project_order(paths) == expected
    assert names(service.list_repos()) == expected
    assert await reordered_events(db) == [(None, {"order": expected})]


async def test_reorder_without_a_bus_only_saves(paths: AppPaths, tmp_path: Path) -> None:
    add_repos(paths, tmp_path, "alpha", "beta")

    repos = await RepoService(paths).reorder(["beta"])

    assert names(repos) == ["beta", "alpha"]
    assert load_project_order(paths) == ["beta", "alpha"]
