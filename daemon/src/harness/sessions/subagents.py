"""The subagents a project chat's run can call, and the teams a message can call (B40)."""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from functools import cached_property

from harness.providers.base import Subagent
from harness.sessions.models import Session


@dataclass(frozen=True)
class TeamCall:
    """A team the user can call with `@handle`: the instruction appended to the message
    the agent gets when they do. The chat shows only what the user typed.
    """

    handle: str
    instruction: str

    @cached_property
    def mention(self) -> re.Pattern[str]:
        # A whole token: after the start or a space, before the end, a space or punctuation.
        return re.compile(rf"(?<!\S)@{re.escape(self.handle)}(?![\w-])")


@dataclass(frozen=True)
class ChatAgents:
    subagents: Mapping[str, Subagent] = field(default_factory=dict[str, Subagent])
    teams: tuple[TeamCall, ...] = ()

    @cached_property
    def fingerprint(self) -> str:
        """Changes with any definition: a run opened with another set needs a new one."""
        data = {
            "subagents": {name: asdict(sub) for name, sub in sorted(self.subagents.items())},
            "teams": [asdict(team) for team in self.teams],
        }
        return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()

    def message(self, text: str) -> str:
        """`text` as the agent gets it: each team it mentions adds its instruction once."""
        return text + "".join(
            team.instruction for team in self.teams if team.mention.search(text) is not None
        )


NO_AGENTS = ChatAgents()

type ChatAgentsSource = Callable[[Session], Awaitable[ChatAgents]]
