"""Filesystem locations for user config and daemon data (D010)."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from nestd.auth.token_socket import SOCKET_NAME

CONFIG_DIR_ENV = "NEST_CONFIG_DIR"
DATA_DIR_ENV = "NEST_DATA_DIR"
WEB_DIST_ENV = "NEST_WEB_DIST"
# The names before the rename to Nest (B43), read when the new one is unset or empty.
LEGACY_ENV_PREFIX = "HARNESS_"
# Claude Code's own setting for where it keeps its data, `~/.claude` by default.
CLAUDE_CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"
DB_NAME = "nest.db"
# The PWA build in this checkout: <repo>/web/dist, next to <repo>/daemon/src/nestd.
DEFAULT_WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"


def env_value(env: Mapping[str, str], name: str) -> str | None:
    """The variable's value, or that of its old `HARNESS_*` name; None when both are unset
    or empty."""
    legacy = LEGACY_ENV_PREFIX + name.removeprefix("NEST_")
    return env.get(name) or env.get(legacy) or None


def default_config_dir(home: Path, name: str = "nest") -> Path:
    return home / ".config" / name


def default_data_dir(home: Path, name: str = "nest") -> Path:
    return home / "Library" / "Application Support" / name


@dataclass(frozen=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    # The built iPhone web app the daemon serves at `/`.
    web_dist: Path = field(default=DEFAULT_WEB_DIST)
    # Claude Code's data, read only (D028): chats to import and which ones are open.
    # None reads no Claude Code chats, so tests never see the real ones.
    claude_dir: Path | None = None
    # Claude Code's own settings file, read only for the account name (D039). None reads nothing.
    claude_account_file: Path | None = None
    # Where the daemon hands this Mac's device token to the Mac app (D075). None serves
    # none, so tests never open a socket by accident.
    token_socket: Path | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str], home: Path) -> Self:
        config_dir = env_value(env, CONFIG_DIR_ENV) or default_config_dir(home)
        data_dir = env_value(env, DATA_DIR_ENV) or default_data_dir(home)
        web_dist = env_value(env, WEB_DIST_ENV) or DEFAULT_WEB_DIST
        claude_config = env.get(CLAUDE_CONFIG_DIR_ENV)
        claude_dir = claude_config or home / ".claude"
        # Claude Code keeps `.claude.json` in its config folder when one is set, else in home.
        account_file = (
            Path(claude_config) / ".claude.json" if claude_config else home / ".claude.json"
        )
        return cls(
            config_dir=Path(config_dir),
            data_dir=Path(data_dir),
            token_socket=Path(data_dir) / SOCKET_NAME,
            web_dist=Path(web_dist),
            claude_dir=Path(claude_dir),
            claude_account_file=account_file,
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
    def pixies_dir(self) -> Path:
        """Each pixie's soul, memory, notes and chat folder (D072)."""
        return self.data_dir / "pixies"

    @property
    def db_path(self) -> Path:
        return self.data_dir / DB_NAME

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
            self.pixies_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
