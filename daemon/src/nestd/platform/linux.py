from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from nestd.platform.base import SYSTEM_PATH, PlatformName


def xdg_dir(env: Mapping[str, str], variable: str, default: Path) -> Path:
    """An XDG base directory; the spec says to ignore a relative one."""
    value = env.get(variable)
    return Path(value) if value and Path(value).is_absolute() else default


@dataclass(frozen=True)
class Linux:
    @property
    def name(self) -> PlatformName:
        return "linux"

    @property
    def moves_legacy_folders(self) -> bool:
        return False

    @property
    def secret_store_help(self) -> str:
        return (
            "Nest keeps its secrets in the Secret Service. Install gnome-keyring (or another "
            "Secret Service provider, such as KeePassXC), unlock the login keyring, then "
            "start Nest again."
        )

    @property
    def machine_noun(self) -> str:
        return "computer"

    def config_dir(self, home: Path, env: Mapping[str, str], name: str = "nest") -> Path:
        return xdg_dir(env, "XDG_CONFIG_HOME", home / ".config") / name

    def data_dir(self, home: Path, env: Mapping[str, str], name: str = "nest") -> Path:
        return xdg_dir(env, "XDG_DATA_HOME", home / ".local" / "share") / name

    def service_path(self, home: Path) -> str:
        return ":".join((str(home / ".local" / "bin"), *SYSTEM_PATH))

    def claude_candidates(self, home: Path) -> tuple[Path, ...]:
        return (
            home / ".local" / "bin" / "claude",
            home / ".claude" / "local" / "claude",
            Path("/usr/local/bin/claude"),
        )

    def codex_candidates(self, home: Path) -> tuple[Path, ...]:
        return (Path("/usr/local/bin/codex"), home / ".local" / "bin" / "codex")

    def llama_cpp_cache(self, home: Path, env: Mapping[str, str]) -> Path:
        return xdg_dir(env, "XDG_CACHE_HOME", home / ".cache") / "llama.cpp"


LINUX = Linux()
