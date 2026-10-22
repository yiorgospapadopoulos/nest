from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from nestd.auth.models import Device
from nestd.sessions.models import QueuedMessage, Session
from nestd.tracking.models import BackgroundSummary, TrackedAgent, TrackedTask


class Health(BaseModel):
    status: Literal["ok"]
    version: str
    machine: str


class Restarting(BaseModel):
    restarting: Literal[True]


class RedeemRequest(BaseModel):
    code: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=32)]
    device_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
    ]


class RedeemResponse(BaseModel):
    device: Device
    token: str


class PairingCodeResponse(BaseModel):
    code: str
    expires_at: datetime


class SessionDetail(Session):
    """A session with its current task list and agents, so clients need not replay events."""

    tasks: list[TrackedTask]
    agents: list[TrackedAgent]
    # Subagents and background commands with running and finished counts.
    background: BackgroundSummary
    # Messages waiting for the current turn to end, oldest first (D032).
    queued: list[QueuedMessage]


class Goal(BaseModel):
    """A chat's visible task list, for a project's goals (D092)."""

    session_id: str
    tasks: list[TrackedTask]


class FileList(BaseModel):
    """Paths relative to the session's working directory, best match first."""

    files: list[str]
