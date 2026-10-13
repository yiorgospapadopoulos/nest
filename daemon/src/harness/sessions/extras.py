"""What a pixie session's run gets beyond a normal chat's (D057)."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from harness.providers.base import AgentTool
from harness.sessions.models import Session


@dataclass(frozen=True)
class RunExtras:
    system_prompt: str
    extra_dirs: tuple[Path, ...]
    tools: tuple[AgentTool, ...]
    # None: the run may edit anywhere its permission mode allows.
    write_root: Path | None
    skills: tuple[str, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    disallowed_tools: tuple[str, ...] = ()


type RunExtrasSource = Callable[[Session], Awaitable[RunExtras]]
