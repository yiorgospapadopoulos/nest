"""What differs between the operating systems the daemon runs on.

Chosen once from `sys.platform` (`current_platform`) and passed down, so tests pick one.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Literal, Protocol

type PlatformName = Literal["macos", "linux"]

SYSTEM_PATH = ("/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin")


class UnsupportedPlatformError(Exception):
    """The daemon does not run on this operating system yet."""


class Platform(Protocol):
    @property
    def name(self) -> PlatformName: ...

    @property
    def moves_legacy_folders(self) -> bool:
        """Whether the folders from before the rename to Nest (B43) may need moving."""
        ...

    @property
    def secret_store_help(self) -> str:
        """What to do when the system's secret store is missing or locked."""
        ...

    @property
    def machine_noun(self) -> str:
        """The machine the daemon runs on, in text for people: "Mac" or "computer", as in
        "this Mac"."""
        ...

    def config_dir(self, home: Path, env: Mapping[str, str], name: str = "nest") -> Path: ...

    def data_dir(self, home: Path, env: Mapping[str, str], name: str = "nest") -> Path: ...

    def service_path(self, home: Path) -> str:
        """PATH for the background service, so `claude`, `git`, `gh` and `uv` resolve as
        in a login shell."""
        ...

    def claude_candidates(self, home: Path) -> tuple[Path, ...]:
        """Where installers put a standalone Claude Code, checked after the PATH."""
        ...

    def codex_candidates(self, home: Path) -> tuple[Path, ...]: ...

    def llama_cpp_cache(self, home: Path, env: Mapping[str, str]) -> Path: ...
