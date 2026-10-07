import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.config.errors import ConfigError
from harness.config.loader import load_settings, save_stuck
from harness.config.models import StuckSettings
from harness.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def test_defaults(paths: AppPaths) -> None:
    assert load_settings(paths).stuck == StuckSettings(
        waiting_minutes=15, silent_minutes=10, repeated_calls=4, turn_minutes=60
    )


def test_thresholds_are_read_from_settings_and_zero_turns_a_check_off(paths: AppPaths) -> None:
    paths.settings_file.write_text("[stuck]\nsilent_minutes = 0\nturn_minutes = 90\n")

    stuck = load_settings(paths).stuck

    assert (stuck.silent_minutes, stuck.turn_minutes, stuck.waiting_minutes) == (0, 90, 15)


@pytest.mark.parametrize(
    "fields",
    [{"waiting_minutes": -1}, {"silent_minutes": 1441}, {"repeated_calls": 1001}, {"x": 1}],
)
def test_thresholds_must_be_in_range(fields: dict[str, int]) -> None:
    with pytest.raises(ValidationError):
        StuckSettings.model_validate(fields)


def test_saving_replaces_only_the_stuck_section(paths: AppPaths) -> None:
    paths.settings_file.write_text("[usage]\nrefresh_minutes = 5\n[stuck]\nturn_minutes = 5\n")

    saved = save_stuck(paths, StuckSettings(repeated_calls=8))

    data = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert saved == StuckSettings(repeated_calls=8)
    assert data["usage"] == {"refresh_minutes": 5}
    assert data["stuck"]["repeated_calls"] == 8
    assert data["stuck"]["turn_minutes"] == 60


def test_saving_refuses_to_overwrite_a_broken_settings_file(paths: AppPaths) -> None:
    paths.settings_file.write_text("[stuck\n", encoding="utf-8")

    with pytest.raises(ConfigError):
        save_stuck(paths, StuckSettings())
