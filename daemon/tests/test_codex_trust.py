import stat
from pathlib import Path

import pytest

from nestd.providers import codex_trust
from nestd.providers.codex_trust import forget_trust

CONFIG = """# my Codex setup
model = "gpt-6.1-sol"

[projects."/Users/me/repo"]
trust_level = "trusted"

[projects."/Users/me/repo/.claude/worktrees/nest-ab12cd"]
trust_level = "trusted"

[projects."/Users/me/repo/.claude/worktrees/nest-ab12cd".extra]
note = "a subtable of the same project"

[mcp_servers.github]
command = "gh-mcp"
"""


def home(tmp_path: Path, text: str = CONFIG) -> Path:
    (tmp_path / "config.toml").write_text(text, encoding="utf-8")
    return tmp_path


def test_the_worktrees_table_goes_and_the_rest_stays_byte_for_byte(tmp_path: Path) -> None:
    codex_home = home(tmp_path)
    (codex_home / "config.toml").chmod(0o600)

    removed = forget_trust(codex_home, Path("/Users/me/repo/.claude/worktrees/nest-ab12cd"))

    assert removed
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == (
        '# my Codex setup\nmodel = "gpt-6.1-sol"\n\n[projects."/Users/me/repo"]\n'
        'trust_level = "trusted"\n\n[mcp_servers.github]\ncommand = "gh-mcp"\n'
    )
    assert stat.S_IMODE((codex_home / "config.toml").stat().st_mode) == 0o600
    assert [p.name for p in codex_home.iterdir()] == ["config.toml"]


def test_a_folder_without_an_entry_leaves_the_file_untouched(tmp_path: Path) -> None:
    codex_home = home(tmp_path)
    before = (codex_home / "config.toml").stat().st_mtime_ns

    assert not forget_trust(codex_home, Path("/Users/me/other"))
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == CONFIG
    assert (codex_home / "config.toml").stat().st_mtime_ns == before


def test_no_config_file_is_nothing_to_forget(tmp_path: Path) -> None:
    assert not forget_trust(tmp_path, tmp_path / "wt")


def test_the_entry_is_found_by_the_resolved_path_and_with_escapes(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real)
    quoted = str(real.resolve()).replace("\\", "\\\\")
    text = (
        f'[projects."{quoted}"] # trusted by Codex\ntrust_level = "trusted"\r\n'
        "[projects.'odd' ]\nx = 1\n"
        "[projects.not valid key]\ny = 2\n"
    )
    codex_home = home(tmp_path, text)

    assert forget_trust(codex_home, link)
    assert (codex_home / "config.toml").read_text(encoding="utf-8") == (
        "[projects.'odd' ]\nx = 1\n[projects.not valid key]\ny = 2\n"
    )


def test_a_failed_write_leaves_the_file_and_no_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    codex_home = home(tmp_path)

    def broken(_self: Path, _target: Path) -> Path:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(Path, "replace", broken)

    with pytest.raises(OSError, match="disk full"):
        codex_trust.forget_trust(codex_home, Path("/Users/me/repo"))

    assert (codex_home / "config.toml").read_text(encoding="utf-8") == CONFIG
    assert [p.name for p in codex_home.iterdir()] == ["config.toml"]
