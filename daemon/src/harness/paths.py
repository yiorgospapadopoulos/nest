"""Filesystem locations for user config and daemon data (D010)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

CONFIG_DIR_ENV = "HARNESS_CONFIG_DIR"
DATA_DIR_ENV = "HARNESS_DATA_DIR"
WEB_DIST_ENV = "HARNESS_WEB_DIST"
# Claude Code's own setting for where it keeps its data, `~/.claude` by default.
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
# The PWA build in this checkout: <repo>/web/dist, next to <repo>/daemon/src/harness.
DEFAULT_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    # The built iPhone web app the daemon serves at `/`.
    web_dist: Path = field(default=DEFAULT_WEB_DIST)
    # Claude Code's data, read only (D028): chats to import and which ones are open.
    # None reads no Claude Code chats, so tests never see the real ones.
    claude_dir: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str], home: Path) -> Self:
        config_dir = env.get(CONFIG_DIR_ENV) or home / ".config" / "harness"
        data_dir = env.get(DATA_DIR_ENV) or home / "Library" / "Application Support" / "harness"
        web_dist = env.get(WEB_DIST_ENV) or DEFAULT_WEB_DIST
        claude_dir = env.get(CLAUDE_CONFIG_DIR_ENV) or home / ".claude"
        return cls(
            config_dir=Path(config_dir),
            data_dir=Path(data_dir),
            web_dist=Path(web_dist),
            claude_dir=Path(claude_dir),
        )

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.toml"

    @property
    def repos_dir(self) -> Path:
        return self.config_dir / "repos"

    @property
    def templates_dir(self) -> Path:
        return self.config_dir / "templates"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def attachments_dir(self) -> Path:
        return self.data_dir / "attachments"

    @property
    def worktrees_dir(self) -> Path:
        return self.data_dir / "worktrees"

    @property
    def agent_gh_dir(self) -> Path:
        """An empty GitHub CLI config dir for agents, so `gh` has no login (D013)."""
        return self.data_dir / "agent-gh"

    @property
    def launchers_dir(self) -> Path:
        """`.command` files that open a session's conversation in Terminal."""
        return self.data_dir / "launchers"

    @property
    def probe_dir(self) -> Path:
        """The empty working directory of the usage probe (D031)."""
        return self.data_dir / "probe"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "harness.db"

    def ensure(self) -> None:
        for directory in (
            self.repos_dir,
            self.templates_dir,
            self.logs_dir,
            self.attachments_dir,
            self.worktrees_dir,
            self.agent_gh_dir,
            self.launchers_dir,
            self.probe_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
