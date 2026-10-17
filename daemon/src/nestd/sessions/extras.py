"""What a pixie session's run gets beyond a normal chat's (D072), and what every run gets."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from nestd.providers.base import AgentTool
from nestd.sessions.models import Session


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
# The tools every chat and pixie run gets, such as the artifact tools (B79).
type NestToolsSource = Callable[[Session], tuple[AgentTool, ...]]
