"""Where releases come from: `NEST_RELEASE_URL` in tests, GitHub otherwise (B130)."""

from collections.abc import Mapping

RELEASE_URL_ENV = "NEST_RELEASE_URL"
DEFAULT_RELEASE_URL = "https://github.com/yiorgospapadopoulos/nest/releases/latest/download"


def release_url(env: Mapping[str, str]) -> str:
    return (env.get(RELEASE_URL_ENV) or DEFAULT_RELEASE_URL).rstrip("/")


def install_line(env: Mapping[str, str]) -> str:
    """The one line that installs Nest, and repairs an install."""
    return f"curl -fsSL {release_url(env)}/install.sh | sh"
