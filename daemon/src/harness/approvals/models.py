from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, JsonValue


class ApprovalKind(StrEnum):
    PERMISSION = "permission"  # a tool call the agent waits to be allowed
    QUESTION = "question"  # the agent's AskUserQuestion, waiting for answers
    PLAN = "plan"  # a plan the agent finished in plan mode, waiting to be approved
    REVIEW = "review"  # finished work to approve, reject or send feedback on
    MERGE = "merge"  # a pull request whose checks passed, waiting to be merged


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    EXPIRED = "expired"  # the agent run waiting on it is gone, or the session closed
    SUPERSEDED = "superseded"  # replaced by a newer review, or by a new message


# Kinds an agent run waits on; they cannot outlive the run.
BLOCKING = (ApprovalKind.PERMISSION, ApprovalKind.QUESTION, ApprovalKind.PLAN)


class Approval(BaseModel):
    id: str
    session_id: str
    # The session's repo and title, for listing the queue.
    repo: str
    title: str
    kind: ApprovalKind
    status: ApprovalStatus
    payload: dict[str, JsonValue]
    resolution: dict[str, JsonValue] | None
    created_at: datetime
    resolved_at: datetime | None
