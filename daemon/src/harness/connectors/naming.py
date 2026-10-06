"""How a connector's raw server name reads, where it comes from and where it is managed."""

from typing import Literal

type ConnectorGroup = Literal["claude.ai", "plugin", "local"]
type ManageHint = Literal["claude.ai", "claude_code"]

CLAUDE_AI_PREFIX = "claude.ai "
PLUGIN_PREFIX = "plugin:"
# Display order of the groups.
GROUPS: tuple[ConnectorGroup, ...] = ("claude.ai", "plugin", "local")


def group_of(name: str) -> ConnectorGroup:
    if name.startswith(CLAUDE_AI_PREFIX):
        return "claude.ai"
    if name.startswith(PLUGIN_PREFIX):
        return "plugin"
    return "local"


def display_name(name: str) -> str:
    """`claude.ai Gmail` reads `Gmail`; `plugin:<plugin>:github` reads `github`."""
    if name.startswith(CLAUDE_AI_PREFIX):
        return name.removeprefix(CLAUDE_AI_PREFIX)
    if name.startswith(PLUGIN_PREFIX):
        return name.removeprefix(PLUGIN_PREFIX).split(":", 1)[-1]
    return name


def manage_hint(group: ConnectorGroup) -> ManageHint:
    """claude.ai connectors are set up on claude.ai; everything else in Claude Code."""
    return "claude.ai" if group == "claude.ai" else "claude_code"
