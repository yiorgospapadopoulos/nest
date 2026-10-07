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


def test_web_dist_defaults_to_the_repository_build(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert AppPaths.from_env({}, home=tmp_path).web_dist == repo_root / "web" / "dist"
    assert AppPaths(config_dir=tmp_path, data_dir=tmp_path).web_dist == repo_root / "web" / "dist"


def test_web_dist_honours_its_environment_override(tmp_path: Path) -> None:
    paths = AppPaths.from_env({"HARNESS_WEB_DIST": str(tmp_path / "build")}, home=tmp_path)

    assert paths.web_dist == tmp_path / "build"


def test_claude_dir_follows_claude_codes_own_setting(tmp_path: Path) -> None:
    overridden = AppPaths.from_env({"CLAUDE_CONFIG_DIR": str(tmp_path / "cc")}, home=tmp_path)

    assert AppPaths.from_env({}, home=tmp_path).claude_dir == tmp_path / ".claude"
    assert overridden.claude_dir == tmp_path / "cc"
    assert AppPaths(config_dir=tmp_path, data_dir=tmp_path).claude_dir is None


def test_the_claude_account_file_follows_home_and_claude_codes_setting(tmp_path: Path) -> None:
    overridden = AppPaths.from_env({"CLAUDE_CONFIG_DIR": str(tmp_path / "cc")}, home=tmp_path)

    assert AppPaths.from_env({}, home=tmp_path).claude_account_file == tmp_path / ".claude.json"
    assert overridden.claude_account_file == tmp_path / "cc" / ".claude.json"
    assert AppPaths(config_dir=tmp_path, data_dir=tmp_path).claude_account_file is None


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
    assert paths.probe_dir == tmp_path / "d" / "probe"


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
        paths.probe_dir,
    ):
        assert directory.is_dir()
