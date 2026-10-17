"""The settings.toml sections B81 adds: `[storage]`, `[pixies]` and the usage warning keys."""

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.config.loader import load_settings, save_pixie_defaults, save_storage, save_usage
from nestd.config.models import PixieDefaults, StorageSettings, UsageSettings
from nestd.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def _on_disk(paths: AppPaths) -> dict[str, object]:
    return tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))


def test_defaults(paths: AppPaths) -> None:
    settings = load_settings(paths)

    assert settings.storage.archive_after_days is None
    assert (settings.usage.warn_percent, settings.usage.warn_notify) == (80, True)
    assert settings.pixies == PixieDefaults(
        model=None,
        autonomy="observe",
        project_access="edit",
        projects="all",
        max_running=2,
        max_per_day=5,
        report_push="action",
        habits_paused=False,
        habit_usage_percent=80,
    )


@pytest.mark.parametrize("days", [0, 3651])
def test_archive_days_must_be_in_range(days: int) -> None:
    with pytest.raises(ValidationError):
        StorageSettings(archive_after_days=days)


def test_storage_is_saved_and_cleared(paths: AppPaths) -> None:
    paths.settings_file.write_text('[agents]\nmodel = "opus"\n', encoding="utf-8")

    assert save_storage(paths, StorageSettings(archive_after_days=30)).archive_after_days == 30
    assert _on_disk(paths)["storage"] == {"archive_after_days": 30}
    assert load_settings(paths).storage.archive_after_days == 30

    assert save_storage(paths, StorageSettings()).archive_after_days is None
    assert _on_disk(paths)["storage"] == {}
    assert _on_disk(paths)["agents"] == {"model": "opus"}
    assert load_settings(paths).storage.archive_after_days is None


@pytest.mark.parametrize("percent", [49, 100])
def test_warn_percent_must_be_in_range(percent: int) -> None:
    with pytest.raises(ValidationError):
        UsageSettings(warn_percent=percent)


def test_a_warning_turned_off_stays_off_after_a_reload(paths: AppPaths) -> None:
    saved = save_usage(paths, UsageSettings(warn_percent=None, warn_notify=False))

    assert saved.warn_percent is None
    # TOML has no null: off is written as 0, which reads back as off.
    assert _on_disk(paths)["usage"] == {
        "refresh_minutes": 3,
        "warn_percent": 0,
        "warn_notify": False,
    }
    assert load_settings(paths).usage.warn_percent is None


def test_a_warning_level_is_saved(paths: AppPaths) -> None:
    save_usage(paths, UsageSettings(warn_percent=90))

    assert load_settings(paths).usage.warn_percent == 90


@pytest.mark.parametrize(
    "fields",
    [
        {"habit_usage_percent": 49},
        {"habit_usage_percent": 101},
        {"max_running": 0},
        {"max_running": 21},
        {"max_per_day": 0},
        {"max_per_day": 101},
        {"autonomy": "everything"},
        {"report_push": "urgent"},
        {"projects": "some"},
        {"model": ""},
    ],
)
def test_invalid_pixie_defaults_are_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PixieDefaults.model_validate(fields)


def test_pixie_defaults_are_saved(paths: AppPaths) -> None:
    chosen = PixieDefaults(
        model="opus",
        autonomy="start",
        project_access="read",
        projects="current",
        max_running=3,
        max_per_day=10,
        report_push="info",
        habits_paused=True,
        habit_usage_percent=95,
    )

    assert save_pixie_defaults(paths, chosen) == chosen
    assert load_settings(paths).pixies == chosen

    save_pixie_defaults(paths, PixieDefaults())
    assert _on_disk(paths)["pixies"] == {
        "autonomy": "observe",
        "project_access": "edit",
        "projects": "all",
        "max_running": 2,
        "max_per_day": 5,
        "report_push": "action",
        "habits_paused": False,
        "habit_usage_percent": 80,
    }
    assert load_settings(paths).pixies.model is None
