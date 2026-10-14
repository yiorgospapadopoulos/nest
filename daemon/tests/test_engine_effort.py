"""IMP-07: the thinking level Claude Code uses by default, from its own settings file."""

import json
import logging
from pathlib import Path

import pytest

from nestd.engine.effort import EffortSettings, claude_code_effort, effort_settings
from nestd.providers.base import ModelOption

LEVELS = ["low", "medium", "high", "xhigh", "max"]
OTHER_DETAIL = "a-private-setting"


def option(value: str, resolved: str | None = None, levels: list[str] | None = None) -> ModelOption:
    return ModelOption(
        value=value,
        display_name=value,
        description="",
        effort_levels=LEVELS if levels is None else levels,
        supports_effort=levels != [],
        resolved_model=resolved,
    )


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_the_default_and_per_model_levels_are_read(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        {
            "effortLevel": "high",
            "modelSettings": {
                "claude-opus-5-5": {"effortLevel": "medium", "maxEffortLevel": "high"},
                "sonnet": {"effortLevel": 3},
                "haiku": "low",
            },
            "env": {"TOKEN": OTHER_DETAIL},
        },
    )

    assert effort_settings(path) == EffortSettings(
        default="high", per_model={"claude-opus-5-5": "medium"}
    )


@pytest.mark.parametrize(
    "data", [{}, [], {"effortLevel": 5, "modelSettings": []}, {"modelSettings": {"x": {}}}]
)
def test_settings_without_levels(tmp_path: Path, data: object) -> None:
    assert effort_settings(write(tmp_path, data)) == EffortSettings()


def test_no_file_means_no_levels(tmp_path: Path) -> None:
    assert effort_settings(tmp_path / "missing.json") == EffortSettings()
    assert effort_settings(None) == EffortSettings()


def test_an_unreadable_file_is_logged_by_kind_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"env": {"TOKEN": "' + OTHER_DETAIL + '"', encoding="utf-8")

    with caplog.at_level(logging.WARNING):
        assert effort_settings(path) == EffortSettings()

    assert "JSONDecodeError" in caplog.text
    assert OTHER_DETAIL not in caplog.text


@pytest.mark.parametrize(
    ("model", "effort"),
    [
        # The model's own level, by the id it resolves to or by its value.
        (option("opus", resolved="claude-opus-5-5"), "medium"),
        (option("claude-sonnet-5"), "low"),
        # Otherwise the general level.
        (option("default", resolved="claude-fable-1"), "high"),
        # A model without thinking levels, or without the level set, shows none.
        (option("haiku", levels=[]), None),
        (option("claude-opus-4-6", levels=["low", "medium"]), None),
    ],
)
def test_each_model_gets_its_level(model: ModelOption, effort: str | None) -> None:
    settings = EffortSettings(
        default="high", per_model={"claude-opus-5-5": "medium", "claude-sonnet-5": "low"}
    )

    assert claude_code_effort(model, settings) == effort


def test_without_any_level_there_is_none() -> None:
    assert claude_code_effort(option("opus"), EffortSettings()) is None
