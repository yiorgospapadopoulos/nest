"""Where the engines keep their setup, and which of those paths Nest may touch (B97).

The allow-list (contract rule 3) is checked on the real path: symlinks and `..` are
resolved first, so a link inside an allowed folder never leads a read or a write outside
it. Claude's `.claude.json` is not on it: Nest changes only its MCP servers, by key.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from nestd.configuration.errors import PathNotAllowedError

CLAUDE_FILES = ("CLAUDE.md", "settings.json", "settings.local.json")
CLAUDE_FOLDERS = ("skills", "agents", "commands")
CODEX_FOLDERS = ("skills", "rules")
REPO_FILES = ("AGENTS.md", "CLAUDE.md", ".mcp.json")
REPO_SKILLS = Path(".claude") / "skills"
INSTRUCTIONS = "AGENTS.md"
CODEX_CONFIG = "config.toml"
# The link in Codex's skills folder that points at the shared one.
SKILLS_LINK = "claude"


@dataclass(frozen=True)
class Locations:
    claude_dir: Path
    # `~/.claude.json`, or the one in `$CLAUDE_CONFIG_DIR`.
    claude_json: Path
    codex_home: Path

    @property
    def claude_md(self) -> Path:
        return self.claude_dir / "CLAUDE.md"

    @property
    def claude_settings(self) -> Path:
        return self.claude_dir / "settings.json"

    @property
    def shared_instructions(self) -> Path:
        return self.codex_home / INSTRUCTIONS

    @property
    def shared_skills(self) -> Path:
        return self.claude_dir / "skills"

    @property
    def synced_skills(self) -> Path:
        """claude.ai account skills Claude Code keeps in step; read only in Nest."""
        return self.shared_skills / "synced"

    @property
    def codex_skills(self) -> Path:
        return self.codex_home / "skills"

    @property
    def skills_link(self) -> Path:
        return self.codex_skills / SKILLS_LINK

    @property
    def codex_config(self) -> Path:
        return self.codex_home / CODEX_CONFIG

    def import_line(self) -> str:
        """The line in CLAUDE.md that makes Claude read the shared instructions."""
        return f"@{self.shared_instructions}"

    def readable(self, raw: str | Path, repos: Iterable[Path] = ()) -> Path:
        """The real path when Nest may read it; 403 otherwise."""
        return self.writable(raw, repos)

    def writable(self, raw: str | Path, repos: Iterable[Path] = ()) -> Path:
        """The real path when Nest may write it; 403 otherwise."""
        path = _real(raw)
        if self._writable(path, repos):
            return path
        raise _refused(raw)

    def _writable(self, path: Path, repos: Iterable[Path]) -> bool:
        claude = self.claude_dir.resolve()
        codex = self.codex_home.resolve()
        allowed = [
            *(_file(path, claude / name) for name in CLAUDE_FILES),
            *(_within(path, claude / name) for name in CLAUDE_FOLDERS),
            _file(path, codex / INSTRUCTIONS),
            _file(path, codex / CODEX_CONFIG),
            *(_within(path, codex / name) for name in CODEX_FOLDERS),
        ]
        for repo in repos:
            root = repo.resolve()
            allowed += [_file(path, root / name) for name in REPO_FILES]
            allowed.append(_within(path, root / REPO_SKILLS))
        return any(allowed)


def _real(raw: str | Path) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        raise _refused(raw)
    return path.resolve()


def _file(path: Path, allowed: Path) -> bool:
    return path == allowed


def _within(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def _refused(raw: str | Path) -> PathNotAllowedError:
    return PathNotAllowedError(f"Nest does not read or change {raw}")
