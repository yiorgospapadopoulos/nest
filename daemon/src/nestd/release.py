"""Where releases come from: `NEST_RELEASE_URL`, else the address the install script used,
else GitHub (B130)."""

from collections.abc import Mapping
from pathlib import Path

RELEASE_URL_ENV = "NEST_RELEASE_URL"
DEFAULT_RELEASE_URL = "https://github.com/yiorgospapadopoulos/nest/releases/latest/download"
# Written by `install.sh` into the data folder, so an install keeps following the address
# it came from, even where the daemon is down and no environment says so.
RELEASE_URL_FILE = "release-url"
ISSUES_URL = "https://github.com/yiorgospapadopoulos/nest/issues/new"


def release_url(env: Mapping[str, str], data_dir: Path | None = None) -> str:
    chosen = env.get(RELEASE_URL_ENV)
    if not chosen and data_dir is not None:
        try:
            chosen = (data_dir / RELEASE_URL_FILE).read_text(encoding="utf-8").strip()
        except OSError:
            chosen = None
    return (chosen or DEFAULT_RELEASE_URL).rstrip("/")


def install_line(env: Mapping[str, str], data_dir: Path | None = None) -> str:
    """The one line that installs Nest, and repairs an install, from the address it came
    from. The script reads its address from the environment, as a piped script cannot tell.
    """
    url = release_url(env, data_dir)
    if url == DEFAULT_RELEASE_URL:
        return f"curl -fsSL {url}/install.sh | sh"
    return f"curl -fsSL {url}/install.sh | {RELEASE_URL_ENV}={url} sh"
