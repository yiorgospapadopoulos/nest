"""B97 rule 3: the paths Nest may read and write, checked on the real path."""

from pathlib import Path

import pytest

from nestd.configuration.errors import PathNotAllowedError
from nestd.configuration.locations import Locations
from tests.configuration_support import locations


@pytest.fixture
def where(tmp_path: Path) -> Locations:
    return locations(tmp_path)


@pytest.mark.parametrize(
    "relative",
    [
        "claude/CLAUDE.md",
        "claude/settings.json",
        "claude/settings.local.json",
        "claude/skills/release/SKILL.md",
        "claude/skills",
        "claude/agents/reviewer.md",
        "claude/commands/deep/ship.md",
        "codex/AGENTS.md",
        "codex/skills/mine/SKILL.md",
        "codex/rules/default.rules",
    ],
)
def test_the_engines_files_are_writable(where: Locations, tmp_path: Path, relative: str) -> None:
    path = tmp_path / relative

    assert where.writable(path) == path.resolve()
    assert where.readable(str(path)) == path.resolve()


@pytest.mark.parametrize(
    "relative",
    [
        "claude.json",
        "claude/.credentials.json",
        "claude/projects/x.jsonl",
        "claude/CLAUDE.md.bak",
        "codex/auth.json",
        "codex/sessions/one.jsonl",
        "elsewhere.txt",
    ],
)
def test_anything_else_is_refused(where: Locations, tmp_path: Path, relative: str) -> None:
    with pytest.raises(PathNotAllowedError):
        where.readable(tmp_path / relative)
    with pytest.raises(PathNotAllowedError):
        where.writable(tmp_path / relative)


def test_codex_config_is_readable_and_writable(where: Locations) -> None:
    assert where.readable(where.codex_config) == where.codex_config.resolve()
    assert where.writable(where.codex_config) == where.codex_config.resolve()


def test_relative_paths_are_refused(where: Locations) -> None:
    with pytest.raises(PathNotAllowedError, match="not read or change"):
        where.readable("claude/CLAUDE.md")


def test_dot_dot_is_resolved_before_checking(where: Locations, tmp_path: Path) -> None:
    sneaky = tmp_path / "claude" / "skills" / ".." / ".credentials.json"

    with pytest.raises(PathNotAllowedError):
        where.writable(sneaky)
    inside = tmp_path / "claude" / "agents" / ".." / "CLAUDE.md"
    assert where.writable(inside) == (tmp_path / "claude" / "CLAUDE.md").resolve()


def test_a_link_leading_outside_is_refused(where: Locations, tmp_path: Path) -> None:
    outside = tmp_path / "secrets"
    outside.mkdir()
    (where.shared_skills).mkdir()
    (where.shared_skills / "escape").symlink_to(outside)

    with pytest.raises(PathNotAllowedError):
        where.writable(where.shared_skills / "escape" / "SKILL.md")


def test_the_shared_skills_link_reads_through_to_the_shared_folder(where: Locations) -> None:
    where.shared_skills.mkdir()
    where.codex_skills.mkdir()
    where.skills_link.symlink_to(where.shared_skills)

    path = where.writable(where.skills_link / "release" / "SKILL.md")

    assert path == (where.shared_skills / "release" / "SKILL.md").resolve()


def test_a_registered_repos_project_files(where: Locations, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()

    for relative in ("AGENTS.md", "CLAUDE.md", ".mcp.json", ".claude/skills/x/SKILL.md"):
        assert where.writable(repo / relative, [repo]) == (repo / relative).resolve()
    with pytest.raises(PathNotAllowedError):
        where.writable(repo / "src" / "main.py", [repo])
    with pytest.raises(PathNotAllowedError):
        where.writable(repo / ".codex" / "config.toml", [repo])
    with pytest.raises(PathNotAllowedError):
        where.writable(repo / "AGENTS.md")


def test_named_locations(where: Locations, tmp_path: Path) -> None:
    assert where.import_line() == f"@{tmp_path / 'codex' / 'AGENTS.md'}"
    assert where.synced_skills == tmp_path / "claude" / "skills" / "synced"
    assert where.claude_settings == tmp_path / "claude" / "settings.json"
