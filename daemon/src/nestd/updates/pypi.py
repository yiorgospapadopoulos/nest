"""The engines Nest installs from PyPI, and the newest version in PyPI's answer.

Standard library only: the installer runs `first_install` with it before the daemon's own
packages are in (D193).
"""

from typing import cast

CLAUDE_PACKAGE = "claude-agent-sdk"
CODEX_PACKAGE = "openai-codex-cli-bin"
PYPI_ENGINES = (CLAUDE_PACKAGE, CODEX_PACKAGE)
PYPI_URL = "https://pypi.org/pypi/{package}/json"


def newest_in(body: object, package: str) -> str | None:
    """The newest version in PyPI's JSON answer; None when that release was pulled. A
    ValueError when the answer is not PyPI's.
    """
    info = cast("dict[str, object]", body).get("info") if isinstance(body, dict) else None
    if not isinstance(info, dict):
        msg = f"PyPI's answer for {package} has no info"
        raise ValueError(msg)
    fields = cast("dict[str, object]", info)
    version = fields.get("version")
    if not isinstance(version, str):
        msg = f"PyPI's answer for {package} has no version"
        raise ValueError(msg)
    return None if fields.get("yanked") is True else version
