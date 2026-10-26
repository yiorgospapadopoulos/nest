"""What a chat's agent is told about its folder's ports (B108)."""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from nestd.sessions.models import Session


@dataclass(frozen=True)
class FolderPorts:
    # `NEST_PORT` and the rest, for the agent's own process.
    env: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    # A paragraph for the Nest instructions; None when the folder has no ports.
    prompt: str | None = None


NO_PORTS = FolderPorts()

type PortsSource = Callable[[Session], Awaitable[FolderPorts]]
