import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.config.errors import ConfigError
from nestd.config.loader import load_settings, save_usage
from nestd.config.models import UsageSettings
from nestd.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def test_usage_refresh_defaults_to_every_three_minutes(paths: AppPaths) -> None:
    assert UsageSettings().refresh_minutes == 3
    assert load_settings(paths).usage.refresh_minutes == 3


def test_usage_refresh_is_read_from_settings(paths: AppPaths) -> None:
    paths.settings_file.write_text("[usage]\nrefresh_minutes = 0\n", encoding="utf-8")

    assert load_settings(paths).usage.refresh_minutes == 0


@pytest.mark.parametrize("minutes", [-1, 1441])
def test_usage_refresh_must_be_in_range(minutes: int) -> None:
    with pytest.raises(ValidationError):
        UsageSettings(refresh_minutes=minutes)


def test_saving_replaces_only_the_usage_section(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[agents]\nmodel = "opus"\n[notifications.kinds]\nfinished = false\n'
        "[usage]\nrefresh_minutes = 3\n",
        encoding="utf-8",
    )

    saved = save_usage(paths, UsageSettings(refresh_minutes=10))

    assert saved == UsageSettings(refresh_minutes=10)
    data = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert data["agents"] == {"model": "opus"}
    assert data["notifications"] == {"kinds": {"finished": False}}
    assert data["usage"] == {"refresh_minutes": 10}
    assert list(paths.config_dir.glob("*.tmp")) == []


def test_saving_usage_refuses_to_overwrite_a_broken_settings_file(paths: AppPaths) -> None:
    paths.settings_file.write_text("[usage\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid TOML"):
        save_usage(paths, UsageSettings())

    assert paths.settings_file.read_text(encoding="utf-8") == "[usage\n"
