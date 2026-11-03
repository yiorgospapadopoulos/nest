from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from nestd.platform.base import SYSTEM_PATH, PlatformName


@dataclass(frozen=True)
class MacOS:
    @property
    def name(self) -> PlatformName:
        return "macos"

    @property
    def moves_legacy_folders(self) -> bool:
        return True

    @property
    def secret_store_help(self) -> str:
        return "Unlock the login keychain in Keychain Access, then start Nest again."

    @property
    def machine_noun(self) -> str:
        return "Mac"

    def config_dir(self, home: Path, env: Mapping[str, str], name: str = "nest") -> Path:
        return home / ".config" / name

    def data_dir(self, home: Path, env: Mapping[str, str], name: str = "nest") -> Path:
        return home / "Library" / "Application Support" / name

    def service_path(self, home: Path) -> str:
        return ":".join((str(home / ".local" / "bin"), "/opt/homebrew/bin", *SYSTEM_PATH))

    def claude_candidates(self, home: Path) -> tuple[Path, ...]:
        return (
            home / ".local" / "bin" / "claude",
            home / ".claude" / "local" / "claude",
            Path("/opt/homebrew/bin/claude"),
            Path("/usr/local/bin/claude"),
        )

    def codex_candidates(self, home: Path) -> tuple[Path, ...]:
        return (
            Path("/opt/homebrew/bin/codex"),
            Path("/usr/local/bin/codex"),
            home / ".local" / "bin" / "codex",
        )

    def llama_cpp_cache(self, home: Path, env: Mapping[str, str]) -> Path:
        return home / "Library" / "Caches" / "llama.cpp"


MACOS = MacOS()
