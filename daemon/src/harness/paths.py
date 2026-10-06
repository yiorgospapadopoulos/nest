"""Filesystem locations for user config and daemon data (D010)."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Self

CONFIG_DIR_ENV = "HARNESS_CONFIG_DIR"
DATA_DIR_ENV = "HARNESS_DATA_DIR"


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str], home: Path) -> Self:
        config_dir = env.get(CONFIG_DIR_ENV) or home / ".config" / "harness"
        data_dir = env.get(DATA_DIR_ENV) or home / "Library" / "Application Support" / "harness"
        return cls(config_dir=Path(config_dir), data_dir=Path(data_dir))

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
        ):
            directory.mkdir(parents=True, exist_ok=True)
