"""The subagents a project chat's run can call, and the teams a message can call (B40)."""

import hashlib
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass, field
from functools import cached_property
from typing import Protocol

from nestd.providers.base import AgentTask, MessageBlock, Subagent
from nestd.sessions.models import NewSession


def mention(name: str) -> re.Pattern[str]:
    """`@name` as a whole token: after the start or a space, before the end, a space or
    punctuation.
    """
    return re.compile(rf"(?<!\S)@{re.escape(name)}(?![\w-])")


@dataclass(frozen=True)
class TeamCall:
    """A team the user can call with `@handle`: the instruction appended to the message
    the agent gets when they do. The chat shows only what the user typed.
    """

    handle: str
    instruction: str

    @cached_property
    def mention(self) -> re.Pattern[str]:
        return mention(self.handle)


@dataclass(frozen=True)
class OfferedPixie:
    """A pixie a project chat's run offers as the subagent `slug` (B46); `team_handle` is
    set when it is in a team the chat can call, which is then the only way to call it.
    """

    id: str
    slug: str
    name: str
    team_id: str | None = None
    team_handle: str | None = None


@dataclass(frozen=True)
class ChatAgents:
    subagents: Mapping[str, Subagent] = field(default_factory=dict[str, Subagent])
    teams: tuple[TeamCall, ...] = ()
    # The pixies among the subagents, by slug; only a project chat's (B46).
    pixies: Mapping[str, OfferedPixie] = field(default_factory=dict[str, OfferedPixie])

    @cached_property
    def fingerprint(self) -> str:
        """Changes with any definition: a run opened with another set needs a new one."""
        data = {
            "subagents": {name: asdict(sub) for name, sub in sorted(self.subagents.items())},
            "teams": [asdict(team) for team in self.teams],
        }
        return _digest(data)

    def pixie_fingerprint(self, slug: str) -> str:
        """Changes with the pixie's definition: its soul, memory or settings (B46)."""
        return _digest(asdict(self.subagents[slug]))

    def message(self, text: str) -> str:
        """`text` as the agent gets it: each team it mentions adds its instruction once."""
        return text + "".join(
            team.instruction for team in self.teams if team.mention.search(text) is not None
        )

    def member_call(self, text: str) -> str | None:
        """Why `text` cannot be sent: it calls a pixie of a team on its own (B46)."""
        for pixie in self.pixies.values():
            if pixie.team_handle is not None and mention(pixie.slug).search(text) is not None:
                return f"{pixie.name} is in @{pixie.team_handle}; call the team or a solo copy"
        return None

    def mentioned_pixies(self, text: str) -> list[OfferedPixie]:
        """The solo pixies `text` calls with `@slug`."""
        return [
            pixie
            for pixie in self.pixies.values()
            if pixie.team_handle is None and mention(pixie.slug).search(text) is not None
        ]

    def team_members(self, text: str) -> list[OfferedPixie]:
        """The pixies of the teams `text` calls with `@handle`."""
        called = {team.handle for team in self.teams if team.mention.search(text) is not None}
        return [pixie for pixie in self.pixies.values() if pixie.team_handle in called]


def _digest(data: object) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


NO_AGENTS = ChatAgents()

type ChatAgentsSource = Callable[[NewSession], Awaitable[ChatAgents]]
"""The pixies a project chat can call with `@slug`, as Claude Code subagents, and the
teams it can call with `@handle` (B40); in a pixie's own chat, every other pixie (B41).
A chat not created yet is asked for with what it will be.
"""


class PixieCalls(Protocol):
    """Follows the pixies a project chat's run calls (B46), with the run's `agents`."""

    async def note(self, session_id: str, agents: ChatAgents, text: str) -> str:
        """What the agent gets after `text` besides the team instructions: how to continue
        the pixies it calls again.
        """
        ...

    async def message(
        self, session_id: str, agents: ChatAgents, blocks: list[MessageBlock]
    ) -> None:
        """The main agent's message, with its tool calls and results."""
        ...

    async def task(self, session_id: str, agents: ChatAgents, update: AgentTask) -> None: ...
