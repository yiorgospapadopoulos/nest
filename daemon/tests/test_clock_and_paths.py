from datetime import UTC, timedelta
from pathlib import Path

from harness.clock import SystemClock
from harness.paths import AppPaths


def test_system_clock_returns_utc_aware_time() -> None:
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert now.tzinfo == UTC


def test_paths_default_to_user_locations(tmp_path: Path) -> None:
    paths = AppPaths.from_env({}, home=tmp_path)

    assert paths.config_dir == tmp_path / ".config" / "harness"
    assert paths.data_dir == tmp_path / "Library" / "Application Support" / "harness"


def test_paths_honour_environment_overrides(tmp_path: Path) -> None:
    env = {"HARNESS_CONFIG_DIR": str(tmp_path / "cfg"), "HARNESS_DATA_DIR": str(tmp_path / "dat")}

    paths = AppPaths.from_env(env, home=tmp_path / "home")

    assert paths.config_dir == tmp_path / "cfg"
    assert paths.data_dir == tmp_path / "dat"


def test_derived_paths_live_under_config_and_data(tmp_path: Path) -> None:
    paths = AppPaths(config_dir=tmp_path / "c", data_dir=tmp_path / "d")

    assert paths.repos_dir == tmp_path / "c" / "repos"
    assert paths.templates_dir == tmp_path / "c" / "templates"
    assert paths.settings_file == tmp_path / "c" / "settings.toml"
    assert paths.logs_dir == tmp_path / "d" / "logs"
    assert paths.attachments_dir == tmp_path / "d" / "attachments"
    assert paths.db_path == tmp_path / "d" / "harness.db"
    assert paths.worktrees_dir == tmp_path / "d" / "worktrees"
    assert paths.agent_gh_dir == tmp_path / "d" / "agent-gh"
    assert paths.launchers_dir == tmp_path / "d" / "launchers"


def test_ensure_creates_every_directory_and_is_idempotent(tmp_path: Path) -> None:
    paths = AppPaths(config_dir=tmp_path / "c", data_dir=tmp_path / "d")

    paths.ensure()
    paths.ensure()

    for directory in (
        paths.config_dir,
        paths.repos_dir,
        paths.templates_dir,
        paths.data_dir,
        paths.logs_dir,
        paths.attachments_dir,
        paths.worktrees_dir,
        paths.agent_gh_dir,
        paths.launchers_dir,
    ):
        assert directory.is_dir()
