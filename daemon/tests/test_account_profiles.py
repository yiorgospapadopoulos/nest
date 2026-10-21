"""B98: profile folders for added accounts, sharing the first account's setup by links.

Everything runs in `tmp_path`: the "first account" folders are stand-ins, never the
user's real ~/.claude or ~/.codex.
"""

import json
import logging
from pathlib import Path

import pytest

from nestd.accounts.profiles import (
    LEAKED_ENV,
    FirstAccount,
    ProfileError,
    Profiles,
    drop_leaked_env,
)


@pytest.fixture
def first(tmp_path: Path) -> FirstAccount:
    claude = tmp_path / "home" / ".claude"
    codex = tmp_path / "home" / ".codex"
    for folder in (claude / "skills", claude / "projects", codex / "sessions", codex / "skills"):
        folder.mkdir(parents=True)
    for name in ("CLAUDE.md", "settings.json", ".credentials.json", ".claude.json"):
        (claude / name).write_text(name, encoding="utf-8")
    (claude / "backups").mkdir()
    for name in (
        "config.toml",
        "AGENTS.md",
        "auth.json",
        "installation_id",
        "state_5.sqlite",
        "state_5.sqlite-wal",
        "state_5.sqlite-shm",
        "logs.sqlite-maintenance.lock",
    ):
        (codex / name).write_text(name, encoding="utf-8")
    (codex / "tmp").mkdir()
    (codex / ".tmp").mkdir()
    account_file = tmp_path / "home" / ".claude.json"
    account_file.write_text(json.dumps({"oauthAccount": {"emailAddress": "me@a.b"}}), "utf-8")
    return FirstAccount(claude_dir=claude, claude_account_file=account_file, codex_home=codex)


@pytest.fixture
def profiles(tmp_path: Path, first: FirstAccount) -> Profiles:
    return Profiles(tmp_path / "data" / "profiles", first)


def test_a_new_folder_is_under_the_profiles_folder_by_engine_and_id(
    tmp_path: Path, profiles: Profiles
) -> None:
    folder = profiles.folder("claude", "0123456789ab")

    assert folder == tmp_path / "data" / "profiles" / "claude" / "0123456789ab"


@pytest.mark.parametrize(
    ("provider", "account_id"),
    [
        ("claude", "claude-main"),
        ("claude", "../../home"),
        ("claude", "0123456789AB"),
        ("claude", "0123456789a"),
        ("gemini", "0123456789ab"),
    ],
)
def test_a_folder_needs_a_known_engine_and_a_twelve_hex_id(
    profiles: Profiles, provider: str, account_id: str
) -> None:
    with pytest.raises(ProfileError):
        profiles.folder(provider, account_id)


def test_a_path_outside_the_profiles_folder_is_refused(
    tmp_path: Path, profiles: Profiles, first: FirstAccount
) -> None:
    assert first.claude_dir is not None
    root = tmp_path / "data" / "profiles"
    for path in (
        first.claude_dir,
        root,
        root / "claude",
        root / "claude" / "0123456789ab" / "inner",
        root / "claude" / ".." / "codex" / ".." / ".." / "x" / "0123456789ab",
        tmp_path / "elsewhere" / "claude" / "0123456789ab",
    ):
        with pytest.raises(ProfileError):
            profiles.checked(path)


def test_a_profile_folder_that_is_a_link_is_refused(tmp_path: Path, profiles: Profiles) -> None:
    folder = profiles.folder("claude", "0123456789ab")
    folder.parent.mkdir(parents=True)
    folder.symlink_to(tmp_path / "home" / ".claude")

    with pytest.raises(ProfileError):
        profiles.checked(folder)


def test_preparing_a_claude_profile_links_the_first_accounts_setup(
    profiles: Profiles, first: FirstAccount
) -> None:
    assert first.claude_dir is not None
    folder = profiles.folder("claude", "0123456789ab")

    env = profiles.prepare("claude", folder)

    assert env == {"CLAUDE_CONFIG_DIR": str(folder)}
    linked = {entry.name: entry.readlink() for entry in folder.iterdir() if entry.is_symlink()}
    assert linked == {
        name: first.claude_dir / name
        for name in ("CLAUDE.md", "settings.json", "skills", "projects")
    }
    assert not (folder / ".credentials.json").exists()
    assert not (folder / "backups").exists()


def test_preparing_again_links_new_entries_and_keeps_the_profiles_own(
    profiles: Profiles, first: FirstAccount, caplog: pytest.LogCaptureFixture
) -> None:
    assert first.claude_dir is not None
    folder = profiles.folder("claude", "0123456789ab")
    profiles.prepare("claude", folder)
    (folder / "CLAUDE.md").unlink()
    (folder / "CLAUDE.md").write_text("the profile's own", encoding="utf-8")
    (first.claude_dir / "agents").mkdir()

    with caplog.at_level(logging.INFO):
        profiles.prepare("claude", folder)

    assert (folder / "agents").readlink() == first.claude_dir / "agents"
    assert (folder / "CLAUDE.md").read_text(encoding="utf-8") == "the profile's own"
    assert (first.claude_dir / "CLAUDE.md").read_text(encoding="utf-8") == "CLAUDE.md"
    assert "CLAUDE.md" in caplog.text


def test_preparing_a_codex_profile_links_all_but_the_login_and_its_databases(
    profiles: Profiles, first: FirstAccount
) -> None:
    assert first.codex_home is not None
    folder = profiles.folder("codex", "0123456789ab")

    env = profiles.prepare("codex", folder)

    assert env == {"CODEX_HOME": str(folder), "CODEX_SQLITE_HOME": str(first.codex_home)}
    linked = sorted(entry.name for entry in folder.iterdir())
    assert linked == ["AGENTS.md", "config.toml", "sessions", "skills"]


def test_the_first_accounts_mcp_servers_are_mirrored_into_the_profiles_own_file(
    profiles: Profiles, first: FirstAccount
) -> None:
    assert first.claude_account_file is not None
    folder = profiles.folder("claude", "0123456789ab")
    folder.mkdir(parents=True)
    (folder / ".claude.json").write_text(
        json.dumps(
            {
                "oauthAccount": {"emailAddress": "work@a.b"},
                "mcpServers": {"old": {}},
                "projects": {
                    "/repo": {"allowedTools": ["x"], "mcpServers": {"stale": {}}},
                    "/gone": {"disabledMcpServers": ["y"], "history": [1]},
                },
            }
        ),
        encoding="utf-8",
    )
    first.claude_account_file.write_text(
        json.dumps(
            {
                "oauthAccount": {"emailAddress": "me@a.b"},
                "mcpServers": {"fs": {"command": "fs"}},
                "projects": {
                    "/repo": {
                        "mcpServers": {"db": {"command": "db"}},
                        "enabledMcpjsonServers": ["a"],
                        "history": ["secret"],
                    },
                    "/new": {"disabledMcpjsonServers": ["b"], "disabledMcpServers": ["c"]},
                    "/plain": {"history": []},
                },
            }
        ),
        encoding="utf-8",
    )

    profiles.prepare("claude", folder)

    mirrored = json.loads((folder / ".claude.json").read_text(encoding="utf-8"))
    assert mirrored == {
        "oauthAccount": {"emailAddress": "work@a.b"},
        "mcpServers": {"fs": {"command": "fs"}},
        "projects": {
            "/repo": {
                "allowedTools": ["x"],
                "mcpServers": {"db": {"command": "db"}},
                "enabledMcpjsonServers": ["a"],
            },
            "/gone": {"history": [1]},
            "/new": {"disabledMcpjsonServers": ["b"], "disabledMcpServers": ["c"]},
        },
    }


def test_servers_the_first_account_dropped_are_dropped_and_unchanged_files_are_kept(
    profiles: Profiles, first: FirstAccount
) -> None:
    assert first.claude_account_file is not None
    folder = profiles.folder("claude", "0123456789ab")
    first.claude_account_file.write_text(json.dumps({"mcpServers": {"fs": {}}}), "utf-8")
    profiles.prepare("claude", folder)
    first.claude_account_file.write_text(json.dumps({"projects": []}), "utf-8")

    profiles.prepare("claude", folder)
    written = (folder / ".claude.json").stat().st_mtime_ns
    profiles.prepare("claude", folder)

    assert json.loads((folder / ".claude.json").read_text(encoding="utf-8")) == {}
    assert (folder / ".claude.json").stat().st_mtime_ns == written


def test_a_profile_without_servers_gets_no_file(profiles: Profiles, first: FirstAccount) -> None:
    assert first.claude_account_file is not None
    first.claude_account_file.write_text("{}", encoding="utf-8")
    folder = profiles.folder("claude", "0123456789ab")

    profiles.prepare("claude", folder)

    assert not (folder / ".claude.json").exists()


@pytest.mark.parametrize("broken", ["source", "profile"])
def test_an_unreadable_file_on_either_side_leaves_the_profiles_file_alone(
    profiles: Profiles, first: FirstAccount, broken: str
) -> None:
    assert first.claude_account_file is not None
    folder = profiles.folder("claude", "0123456789ab")
    folder.mkdir(parents=True)
    own = folder / ".claude.json"
    own.write_text(json.dumps({"oauthAccount": {}}), encoding="utf-8")
    first.claude_account_file.write_text(json.dumps({"mcpServers": {"fs": {}}}), "utf-8")
    (first.claude_account_file if broken == "source" else own).write_text("{", "utf-8")
    before = own.read_text(encoding="utf-8")

    profiles.prepare("claude", folder)

    assert own.read_text(encoding="utf-8") == before


def test_a_file_that_holds_no_object_counts_as_empty(
    profiles: Profiles, first: FirstAccount
) -> None:
    assert first.claude_account_file is not None
    first.claude_account_file.write_text("[]", encoding="utf-8")
    folder = profiles.folder("claude", "0123456789ab")

    profiles.prepare("claude", folder)

    assert not (folder / ".claude.json").exists()


def test_without_the_first_accounts_folders_a_profile_cannot_be_prepared(
    tmp_path: Path,
) -> None:
    profiles = Profiles(tmp_path / "profiles", FirstAccount(None, None, None))

    for provider in ("claude", "codex"):
        with pytest.raises(ProfileError):
            profiles.prepare(provider, profiles.folder(provider, "0123456789ab"))


def test_without_the_account_file_the_links_are_still_made(
    tmp_path: Path, first: FirstAccount
) -> None:
    profiles = Profiles(tmp_path / "profiles", FirstAccount(first.claude_dir, None, None))
    folder = profiles.folder("claude", "0123456789ab")

    profiles.prepare("claude", folder)

    assert (folder / "CLAUDE.md").is_symlink()
    assert not (folder / ".claude.json").exists()


def test_a_missing_first_folder_links_nothing(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    profiles = Profiles(tmp_path / "profiles", FirstAccount(missing, None, missing))
    folder = profiles.folder("codex", "0123456789ab")

    profiles.prepare("codex", folder)

    assert list(folder.iterdir()) == []


def test_the_first_account_has_no_environment_of_its_own(profiles: Profiles) -> None:
    assert profiles.env("claude", None) == {}
    assert profiles.env("codex", None) == {}


def test_removing_a_profile_deletes_its_links_never_what_they_point_to(
    profiles: Profiles, first: FirstAccount
) -> None:
    assert first.claude_dir is not None
    folder = profiles.folder("claude", "0123456789ab")
    profiles.prepare("claude", folder)
    (folder / "own.txt").write_text("x", encoding="utf-8")
    before = sorted(path.name for path in first.claude_dir.rglob("*"))

    profiles.remove(folder)
    profiles.remove(folder)

    assert not folder.exists()
    assert sorted(path.name for path in first.claude_dir.rglob("*")) == before
    assert (first.claude_dir / "CLAUDE.md").read_text(encoding="utf-8") == "CLAUDE.md"


def test_removing_refuses_the_first_accounts_folder(
    profiles: Profiles, first: FirstAccount
) -> None:
    assert first.claude_dir is not None

    with pytest.raises(ProfileError):
        profiles.remove(first.claude_dir)

    assert (first.claude_dir / "CLAUDE.md").exists()


def test_the_daemon_drops_the_account_variables_a_claude_shell_leaks() -> None:
    env = dict.fromkeys(LEAKED_ENV, "x") | {"PATH": "/bin"}

    drop_leaked_env(env)

    assert env == {"PATH": "/bin"}
    assert set(LEAKED_ENV) == {
        "CLAUDE_CODE_USER_EMAIL",
        "CLAUDE_CODE_ACCOUNT_UUID",
        "CLAUDE_CODE_ORGANIZATION_UUID",
    }
