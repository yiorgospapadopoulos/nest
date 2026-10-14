import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from harness.config.errors import ConfigError
from harness.config.loader import load_repos, load_settings, save_agent_defaults, save_repo
from harness.config.models import AgentChoices, AgentDefaults, RepoConfig, WorktreeConfig
from harness.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def test_new_chats_work_in_place_unless_settings_say_otherwise(paths: AppPaths) -> None:
    assert AgentDefaults().default_mode == "in_place"
    assert load_settings(paths).agents.default_mode == "in_place"

    paths.settings_file.write_text('[agents]\ndefault_mode = "worktree"\n', encoding="utf-8")

    assert load_settings(paths).agents.default_mode == "worktree"


def test_the_mode_is_claude_codes_own_unless_settings_say_otherwise(paths: AppPaths) -> None:
    """IMP-06: no mode is passed, so Claude Code's `defaultMode` applies."""
    assert AgentDefaults().permission_mode is None
    assert load_settings(paths).agents.permission_mode is None
    assert "permission_mode" not in paths.settings_file.read_text(encoding="utf-8")

    paths.settings_file.write_text('[agents]\npermission_mode = "auto"\n', encoding="utf-8")

    assert load_settings(paths).agents.permission_mode == "auto"


def test_idle_agents_are_closed_after_an_hour_unless_settings_say_otherwise(
    paths: AppPaths,
) -> None:
    """BUG-11: each close re-runs the user's SessionEnd and SessionStart hooks."""
    assert load_settings(paths).agents.idle_close_minutes == 60

    paths.settings_file.write_text("[agents]\nidle_close_minutes = 15\n", encoding="utf-8")

    assert load_settings(paths).agents.idle_close_minutes == 15


def test_an_unknown_default_mode_is_refused() -> None:
    with pytest.raises(ValidationError):
        AgentDefaults.model_validate({"default_mode": "elsewhere"})


def test_a_repo_follows_the_global_mode_unless_its_file_sets_one(paths: AppPaths) -> None:
    (paths.repos_dir / "a.toml").write_text('name = "a"\npath = "/src/a"\n', encoding="utf-8")
    (paths.repos_dir / "b.toml").write_text(
        'name = "b"\npath = "/src/b"\n[worktree]\ndefault = true\n', encoding="utf-8"
    )

    first, second = load_repos(paths)

    assert first.worktree.default is None
    assert second.worktree.default is True


def test_a_saved_repo_without_an_override_writes_no_default(paths: AppPaths) -> None:
    save_repo(paths, RepoConfig(name="a", path=Path("/src/a"), worktree=WorktreeConfig()))

    data = tomllib.loads((paths.repos_dir / "a.toml").read_text(encoding="utf-8"))

    assert "default" not in data["worktree"]


def test_saving_agent_defaults_keeps_other_keys_and_sections(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[agents]\nmodel = "opus"\neffort = "high"\nidle_close_minutes = 25\n'
        "[usage]\nrefresh_minutes = 7\n",
        encoding="utf-8",
    )

    saved = save_agent_defaults(
        paths,
        AgentChoices(model=None, effort="max", permission_mode="plan", mode="worktree"),
    )

    assert saved == AgentDefaults(
        effort="max", permission_mode="plan", default_mode="worktree", idle_close_minutes=25
    )
    data = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert data["agents"] == {
        "effort": "max",
        "permission_mode": "plan",
        "default_mode": "worktree",
        "idle_close_minutes": 25,
    }
    assert data["usage"] == {"refresh_minutes": 7}
    assert list(paths.config_dir.glob("*.tmp")) == []


def test_saving_agent_defaults_creates_the_file(paths: AppPaths) -> None:
    saved = save_agent_defaults(paths, AgentChoices(model="sonnet"))

    assert saved == AgentDefaults(model="sonnet")
    assert load_settings(paths).agents == saved


def test_saving_agent_defaults_refuses_to_overwrite_a_broken_settings_file(
    paths: AppPaths,
) -> None:
    paths.settings_file.write_text("[agents\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid TOML"):
        save_agent_defaults(paths, AgentChoices())

    assert paths.settings_file.read_text(encoding="utf-8") == "[agents\n"


def test_saving_agent_defaults_refuses_an_invalid_agents_section(paths: AppPaths) -> None:
    paths.settings_file.write_text("[agents]\nidle_close_minutes = 0\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="idle_close_minutes"):
        save_agent_defaults(paths, AgentChoices())


def test_choices_reject_unknown_values() -> None:
    for data in ({"effort": "huge"}, {"mode": "elsewhere"}, {"permission_mode": "dontAsk"}):
        with pytest.raises(ValidationError):
            AgentChoices.model_validate(data)
