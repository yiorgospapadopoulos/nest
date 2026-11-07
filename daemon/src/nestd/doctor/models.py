"""One check's answer, as the apps and `nest doctor` show it."""

from typing import Literal

from pydantic import BaseModel, computed_field

type CheckState = Literal["ok", "missing", "warning", "not_applicable"]
# How much a missing check matters: Nest cannot run, it works less well, or it is extra.
type Importance = Literal["required", "recommended", "optional"]


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
    importance: Importance = "recommended"
    # How far a check with several steps has got, such as Tailscale's: the apps show each
    # step's part only once it is reached.
    stage: str | None = None

    @computed_field
    @property
    def rank(self) -> int:
        """Where it goes in Check Nest and `nest doctor`, lowest first: what stops Nest, then
        what it lacks, then warnings, then the optional, then what is fine.
        """
        if self.state == "missing":
            return {"required": 0, "recommended": 1, "optional": 3}[self.importance]
        if self.state == "warning":
            return 2
        if self.state == "not_applicable":
            return 3
        return 4


class SetupChecks(BaseModel):
    """`GET /api/setup/checks`."""

    checks: list[Check]
