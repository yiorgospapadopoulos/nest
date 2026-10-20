from datetime import UTC, timedelta
from pathlib import Path

from nestd.clock import SystemClock
from nestd.paths import AppPaths


def test_system_clock_returns_utc_aware_time() -> None:
    now = SystemClock().now()

    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)
    assert now.tzinfo == UTC


def test_paths_default_to_user_locations(tmp_path: Path) -> None:
    paths = AppPaths.from_env({}, home=tmp_path)

    assert paths.config_dir == tmp_path / ".config" / "nest"
    assert paths.data_dir == tmp_path / "Library" / "Application Support" / "nest"


def test_paths_honour_environment_overrides(tmp_path: Path) -> None:
    env = {"NEST_CONFIG_DIR": str(tmp_path / "cfg"), "NEST_DATA_DIR": str(tmp_path / "dat")}

    paths = AppPaths.from_env(env, home=tmp_path / "home")

    assert paths.config_dir == tmp_path / "cfg"
    assert paths.data_dir == tmp_path / "dat"


def test_paths_fall_back_to_the_old_harness_variables(tmp_path: Path) -> None:
    """B43: a service or shell still setting the old names keeps working."""
    old = {
        "HARNESS_CONFIG_DIR": str(tmp_path / "old-cfg"),
        "HARNESS_DATA_DIR": str(tmp_path / "old-dat"),
        "HARNESS_WEB_DIST": str(tmp_path / "old-web"),
    }
    both = {**old, "NEST_CONFIG_DIR": str(tmp_path / "cfg"), "NEST_DATA_DIR": str(tmp_path / "dat")}

    legacy = AppPaths.from_env(old, home=tmp_path)
    preferred = AppPaths.from_env(both, home=tmp_path)

    assert (legacy.config_dir, legacy.data_dir) == (tmp_path / "old-cfg", tmp_path / "old-dat")
    assert legacy.web_dist == tmp_path / "old-web"
    assert legacy.token_socket == tmp_path / "old-dat" / "token.sock"
    assert (preferred.config_dir, preferred.data_dir) == (tmp_path / "cfg", tmp_path / "dat")
    assert preferred.web_dist == tmp_path / "old-web"


def test_an_empty_new_variable_falls_back_too(tmp_path: Path) -> None:
    env = {"NEST_DATA_DIR": "", "HARNESS_DATA_DIR": str(tmp_path / "old")}

    assert AppPaths.from_env(env, home=tmp_path).data_dir == tmp_path / "old"


def test_web_dist_defaults_to_the_repository_build(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]

    assert AppPaths.from_env({}, home=tmp_path).web_dist == repo_root / "web" / "dist"
    assert AppPaths(config_dir=tmp_path, data_dir=tmp_path).web_dist == repo_root / "web" / "dist"


def test_web_dist_honours_its_environment_override(tmp_path: Path) -> None:
    paths = AppPaths.from_env({"NEST_WEB_DIST": str(tmp_path / "build")}, home=tmp_path)

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


def test_the_token_socket_lives_in_the_data_folder(tmp_path: Path) -> None:
    """The Mac app reads its token there (D075); paths built in tests serve none."""
    env = {"NEST_DATA_DIR": str(tmp_path / "dat")}

    assert AppPaths.from_env({}, home=tmp_path).token_socket == (
        tmp_path / "Library" / "Application Support" / "nest" / "token.sock"
    )
    assert AppPaths.from_env(env, home=tmp_path).token_socket == tmp_path / "dat" / "token.sock"
    assert AppPaths(config_dir=tmp_path, data_dir=tmp_path).token_socket is None


def test_derived_paths_live_under_config_and_data(tmp_path: Path) -> None:
    paths = AppPaths(config_dir=tmp_path / "c", data_dir=tmp_path / "d")

    assert paths.repos_dir == tmp_path / "c" / "repos"
    assert paths.templates_dir == tmp_path / "c" / "templates"
    assert paths.settings_file == tmp_path / "c" / "settings.toml"
    assert paths.logs_dir == tmp_path / "d" / "logs"
    assert paths.attachments_dir == tmp_path / "d" / "attachments"
    assert paths.db_path == tmp_path / "d" / "nest.db"
    assert paths.worktrees_dir == tmp_path / "d" / "worktrees"
    assert paths.agent_gh_dir == tmp_path / "d" / "agent-gh"
    assert paths.launchers_dir == tmp_path / "d" / "launchers"
    assert paths.probe_dir == tmp_path / "d" / "probe"
    assert paths.pixies_dir == tmp_path / "d" / "pixies"


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
        paths.pixies_dir,
    ):
        assert directory.is_dir()


def test_codexs_home_follows_its_own_setting_and_is_unset_in_tests(tmp_path: Path) -> None:
    overridden = AppPaths.from_env({"CODEX_HOME": str(tmp_path / "cx")}, home=tmp_path)

    assert AppPaths.from_env({}, home=tmp_path).codex_home == tmp_path / ".codex"
    assert overridden.codex_home == tmp_path / "cx"
    assert AppPaths(config_dir=tmp_path, data_dir=tmp_path).codex_home is None
