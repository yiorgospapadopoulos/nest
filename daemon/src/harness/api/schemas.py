from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, StringConstraints

from harness.auth.models import Device
from harness.sessions.models import Session
from harness.tracking.models import TrackedAgent, TrackedTask


class Health(BaseModel):
    status: Literal["ok"]
    version: str


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
