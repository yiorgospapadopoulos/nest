"""The pixies a project chat called, as its group shows them (B46)."""

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from nestd.tracking.transcripts import AgentMessage

type CallState = Literal["running", "done", "failed", "interrupted"]


class PixieCall(BaseModel):
    """A stored call: the pixie's Agent call, or a SendMessage that continued it."""

    id: str
    session_id: str
    pixie_id: str
    team_id: str | None
    tool_use_id: str
    agent_id: str | None
    # The tool use id of the first call of the agent this one continued.
    continues: str | None
    state: CallState
    background: bool
    fingerprint: str
    sent_away: bool
    started_at: datetime
    finished_at: datetime | None


class CallEntry(BaseModel):
    id: str
    pixie_id: str
    tool_use_id: str
    agent_id: str | None
    state: CallState
    # A SendMessage that continued an earlier call's agent with its context.
    continued: bool
    started_at: datetime
    finished_at: datetime | None

    @classmethod
    def of(cls, call: PixieCall) -> Self:
        return cls(
            id=call.id,
            pixie_id=call.pixie_id,
            tool_use_id=call.tool_use_id,
            agent_id=call.agent_id,
            state=call.state,
            continued=call.continues is not None,
            started_at=call.started_at,
            finished_at=call.finished_at,
        )


class TeamMember(BaseModel):
    pixie_id: str
    leader: bool
    # Its latest call's state with the team; None when it was not called yet.
    state: CallState | None


class GroupEntry(BaseModel):
    """A solo pixie (`pixie_id`) or a team (`team_id`, with its members) the chat called,
    in the order first called. `state` is the latest call's; calls are newest first.
    """

    kind: Literal["pixie", "team"]
    pixie_id: str | None
    team_id: str | None
    state: CallState
    members: list[TeamMember]
    calls: list[CallEntry]


class CallWork(CallEntry):
    """A call with what it was asked, the agent's own messages and its report."""

    prompt: str | None
    messages: list[AgentMessage]
    report: str | None


class SendAway(BaseModel):
    """A pixie, or a team with its members, to leave the chat's group: exactly one."""

    model_config = ConfigDict(extra="forbid")

    pixie_id: str | None = None
    team_id: str | None = None

    @model_validator(mode="after")
    def _one(self) -> Self:
        if (self.pixie_id is None) == (self.team_id is None):
            msg = "name either a pixie_id or a team_id"
            raise ValueError(msg)
        return self
