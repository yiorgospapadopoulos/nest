"""One check's answer, as the apps and `nest doctor` show it."""

from typing import Literal

from pydantic import BaseModel

type CheckState = Literal["ok", "missing", "warning", "not_applicable"]


class Fix(BaseModel):
    """What sorts it out: a command to paste, or a page to open."""

    kind: Literal["command", "link"]
    value: str


class Check(BaseModel):
    id: str
    title: str
    state: CheckState
    # What is wrong and what to do, in plain words; empty when there is nothing to say.
    message: str = ""
    # The short answer beside a title, such as a version or "Starts at login".
    detail: str | None = None
    fix: Fix | None = None


class SetupChecks(BaseModel):
    """`GET /api/setup/checks`."""

    checks: list[Check]
