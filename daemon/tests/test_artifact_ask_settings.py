"""`[artifacts]` in settings.toml (B88 stage 4): whether pages may ask Claude, on which model,
how often a day and how long an answer may be.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.config.loader import load_settings
from nestd.config.models import ArtifactSettings
from nestd.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def test_the_defaults_are_haiku_twenty_a_day_and_short_answers(paths: AppPaths) -> None:
    settings = load_settings(paths).artifacts

    assert settings == ArtifactSettings(
        ask=True, ask_model="haiku", ask_daily_limit=20, ask_max_output_tokens=1000
    )
    assert paths.ask_dir.is_dir()


def test_the_section_is_read_from_the_file(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[artifacts]\nask = false\nask_model = " sonnet "\nask_daily_limit = 2\n'
        "ask_max_output_tokens = 100\n",
        encoding="utf-8",
    )

    settings = load_settings(paths).artifacts

    assert settings == ArtifactSettings(
        ask=False, ask_model="sonnet", ask_daily_limit=2, ask_max_output_tokens=100
    )


@pytest.mark.parametrize(
    "fields",
    [
        {"ask_daily_limit": 0},
        {"ask_daily_limit": 201},
        {"ask_max_output_tokens": 99},
        {"ask_max_output_tokens": 4001},
        {"ask_model": " "},
        {"ask": "yes"},
        {"asks": 3},
    ],
)
def test_bad_values_are_refused(fields: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ArtifactSettings.model_validate(fields)


def test_the_limits_at_their_edges_are_fine() -> None:
    low = ArtifactSettings(ask_daily_limit=1, ask_max_output_tokens=100)
    high = ArtifactSettings(ask_daily_limit=200, ask_max_output_tokens=4000)

    assert (low.ask_daily_limit, high.ask_max_output_tokens) == (1, 4000)
