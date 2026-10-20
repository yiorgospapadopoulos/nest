import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.config.errors import ConfigError
from nestd.config.loader import (
    load_repos,
    load_settings,
    load_templates,
    save_configuration,
    save_repo,
)
from nestd.config.models import (
    ConfigurationSettings,
    McpSharing,
    RepoConfig,
    ServerSettings,
    Settings,
    WorktreeConfig,
)
from nestd.paths import AppPaths


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    result = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    result.ensure()
    return result


def test_first_run_writes_default_settings_file(paths: AppPaths) -> None:
    settings = load_settings(paths)

    assert settings == Settings()
    assert settings.server.port == 8765
    # No mode: Claude Code applies its own `defaultMode` (IMP-06).
    assert settings.agents.permission_mode is None
    assert settings.modules.enabled == []
    written = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert written["server"]["port"] == 8765
    assert load_settings(paths) == settings


def test_settings_are_read_from_file(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[server]\nport = 9000\n[agents]\nmodel = "opus"\neffort = "high"\n'
        'permission_mode = "plan"\n[modules]\nenabled = ["ntfy"]\n',
        encoding="utf-8",
    )

    settings = load_settings(paths)

    assert settings.server.port == 9000
    assert settings.agents.model == "opus"
    assert settings.agents.effort == "high"
    assert settings.agents.permission_mode == "plan"
    assert settings.modules.enabled == ["ntfy"]


def test_invalid_toml_names_the_file(paths: AppPaths) -> None:
    paths.settings_file.write_text("[server\n", encoding="utf-8")

    with pytest.raises(ConfigError, match=r"settings\.toml: invalid TOML"):
        load_settings(paths)


def test_schema_errors_are_summarised(paths: AppPaths) -> None:
    paths.settings_file.write_text(
        '[server]\nport = "x"\nhost = "0.0.0.0"\n[agents]\neffort = "huge"\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError) as caught:
        load_settings(paths)

    message = str(caught.value)
    assert "settings.toml" in message
    assert "server.port" in message
    assert "server.host" in message
    assert "agents.effort" in message


def test_port_must_be_in_range() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"server": {"port": 70000}})


def test_root_level_schema_error_is_labelled(paths: AppPaths) -> None:
    paths.settings_file.write_text("unknown = 1\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="unknown"):
        load_settings(paths)


def test_repos_are_loaded_sorted_by_file(paths: AppPaths) -> None:
    (paths.repos_dir / "b.toml").write_text(
        'name = "beta"\npath = "/src/beta"\n[worktree]\ndefault = false\n'
        'link = [".env", "config/local.json"]\nsetup = ["uv sync"]\n',
        encoding="utf-8",
    )
    (paths.repos_dir / "a.toml").write_text(
        'name = "alpha"\npath = "/src/alpha"\ndefault_branch = "trunk"\n', encoding="utf-8"
    )
    (paths.repos_dir / "notes.txt").write_text("ignored", encoding="utf-8")

    repos = load_repos(paths)

    assert [repo.name for repo in repos] == ["alpha", "beta"]
    assert repos[0].default_branch == "trunk"
    assert repos[0].worktree == WorktreeConfig()
    assert repos[1].path == Path("/src/beta")
    assert repos[1].worktree.default is False
    assert repos[1].worktree.link == [".env", "config/local.json"]
    assert repos[1].worktree.setup == ["uv sync"]


def test_missing_config_directories_mean_no_entries(tmp_path: Path) -> None:
    paths = AppPaths(config_dir=tmp_path / "absent", data_dir=tmp_path / "data")

    assert load_repos(paths) == []
    assert load_templates(paths) == []


def test_duplicate_repo_names_are_rejected(paths: AppPaths) -> None:
    for file in ("one.toml", "two.toml"):
        (paths.repos_dir / file).write_text('name = "same"\npath = "/x"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match=r"two\.toml: duplicate repo name 'same'"):
        load_repos(paths)


@pytest.mark.parametrize("link", ["/etc/passwd", "../outside", "a/../../b", "", "."])
def test_worktree_links_must_stay_inside_the_repo(link: str) -> None:
    with pytest.raises(ValidationError, match="link"):
        WorktreeConfig(link=[link])


@pytest.mark.parametrize("name", ["", "a/b", "..", ".hidden", "with space"])
def test_repo_names_must_be_safe_file_names(name: str) -> None:
    with pytest.raises(ValidationError):
        RepoConfig(name=name, path=Path("/x"))


def test_a_repo_file_may_set_a_pixie_icon_and_colour(paths: AppPaths) -> None:
    (paths.repos_dir / "a.toml").write_text(
        'name = "alpha"\npath = "/src/alpha"\nicon = "moth"\nicon_color = "#ff8800"\n',
        encoding="utf-8",
    )
    (paths.repos_dir / "b.toml").write_text('name = "beta"\npath = "/src/beta"\n', encoding="utf-8")

    alpha, beta = load_repos(paths)

    assert (alpha.icon, alpha.icon_color) == ("moth", "#ff8800")
    assert (beta.icon, beta.icon_color) == (None, None)


def test_a_repo_icon_saved_with_an_old_mascot_name_reads_as_its_new_name(
    paths: AppPaths,
) -> None:
    """B89: a project icon chosen before the fairy redesign keeps working and is
    written back with the new name on its next save.
    """
    (paths.repos_dir / "a.toml").write_text(
        'name = "alpha"\npath = "/src/alpha"\nicon = "owl"\n', encoding="utf-8"
    )

    (alpha,) = load_repos(paths)
    save_repo(paths, alpha)

    assert alpha.icon == "moth"
    assert 'icon = "moth"' in (paths.repos_dir / "alpha.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "line", ['icon = "dragon"', 'icon_color = "orange"', 'icon_color = "#ff88"']
)
def test_an_unknown_repo_icon_or_colour_names_the_file(paths: AppPaths, line: str) -> None:
    (paths.repos_dir / "bad.toml").write_text(
        f'name = "bad"\npath = "/src/bad"\n{line}\n', encoding="utf-8"
    )

    with pytest.raises(ConfigError, match=r"bad\.toml: icon"):
        load_repos(paths)


def test_templates_are_loaded_and_validated(paths: AppPaths) -> None:
    (paths.templates_dir / "fix.toml").write_text(
        'name = "fix"\nprompt = "Fix the bug"\nrepo = "alpha"\neffort = "max"\n'
        'permission_mode = "acceptEdits"\n',
        encoding="utf-8",
    )
    (paths.templates_dir / "plain.toml").write_text(
        'name = "plain"\nprompt = "Hello"\n', encoding="utf-8"
    )

    templates = load_templates(paths)

    assert [template.name for template in templates] == ["fix", "plain"]
    assert templates[0].repo == "alpha"
    assert templates[0].effort == "max"
    assert templates[0].permission_mode == "acceptEdits"
    assert templates[1].model is None
    assert templates[1].permission_mode is None


def test_duplicate_template_names_are_rejected(paths: AppPaths) -> None:
    for file in ("a.toml", "b.toml"):
        (paths.templates_dir / file).write_text('name = "t"\nprompt = "p"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match="duplicate template name 't'"):
        load_templates(paths)


def test_template_schema_errors_name_the_file(paths: AppPaths) -> None:
    (paths.templates_dir / "bad.toml").write_text('name = "t"\n', encoding="utf-8")

    with pytest.raises(ConfigError, match=r"bad\.toml: prompt"):
        load_templates(paths)


def test_save_repo_round_trips(tmp_path: Path) -> None:
    paths = AppPaths(config_dir=tmp_path / "fresh", data_dir=tmp_path / "data")
    repo = RepoConfig(
        name="alpha",
        path=Path("/src/alpha"),
        worktree=WorktreeConfig(link=[".env"], setup=["make install"]),
    )

    save_repo(paths, repo)

    assert (paths.repos_dir / "alpha.toml").is_file()
    assert load_repos(paths) == [repo]


def test_agent_and_worktree_defaults_for_sessions() -> None:
    settings = Settings()

    assert settings.agents.idle_close_minutes == 60
    assert WorktreeConfig().setup_timeout_seconds == 900


@pytest.mark.parametrize(
    "data",
    [{"agents": {"idle_close_minutes": 0}}, {"agents": {"idle_close_minutes": -1}}],
)
def test_idle_close_must_be_positive(data: dict[str, dict[str, int]]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(data)


def test_setup_timeout_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        WorktreeConfig(setup_timeout_seconds=0)


def test_allowed_origins_default_to_empty_and_are_read(paths: AppPaths) -> None:
    assert load_settings(paths).server.allowed_origins == []

    paths.settings_file.write_text(
        '[server]\nallowed_origins = ["https://mac.example.ts.net"]\n', encoding="utf-8"
    )

    assert load_settings(paths).server.allowed_origins == ["https://mac.example.ts.net"]


def test_allowed_hosts_default_to_empty_and_are_read(paths: AppPaths) -> None:
    assert load_settings(paths).server.allowed_hosts == []

    paths.settings_file.write_text(
        '[server]\nallowed_hosts = ["Nest.Local", "*.example.org"]\n', encoding="utf-8"
    )

    assert load_settings(paths).server.allowed_hosts == ["nest.local", "*.example.org"]


@pytest.mark.parametrize(
    "entry", ["", "*", "https://mac.ts.net", "mac.ts.net:8765", "a b", "*.", "x.*.org"]
)
def test_allowed_hosts_must_be_host_names(entry: str) -> None:
    with pytest.raises(ValidationError):
        ServerSettings(allowed_hosts=[entry])


def test_configuration_settings_default_to_sharing_mcp_servers(paths: AppPaths) -> None:
    settings = load_settings(paths)

    assert settings.configuration.mcp_shared.claude is True
    assert settings.configuration.mcp_shared.codex is True
    assert settings.configuration.codex_claude_only_off is False


def test_save_configuration_keeps_the_other_sections(paths: AppPaths) -> None:
    paths.settings_file.write_text("[server]\nport = 9001\n", encoding="utf-8")
    changed = ConfigurationSettings(
        mcp_shared=McpSharing(claude=True, codex=False), codex_claude_only_off=True
    )

    saved = save_configuration(paths, changed)

    assert saved == changed
    written = tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))
    assert written["configuration"]["mcp_shared"] == {"claude": True, "codex": False}
    assert written["server"]["port"] == 9001
    assert load_settings(paths).configuration == changed
