"""Read a pull request's status with the user's `gh` login (D004, D034)."""

from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field

from harness.gitops.runner import CommandRunner
from harness.prs.models import ChecksState, CheckState, PrCheck, PrChecks, PrState, PrStatus

FIELDS = (
    "state,mergeable,mergeStateStatus,statusCheckRollup,reviewDecision,headRefOid,url,number,"
    "title,createdAt"
)
_STATES: dict[str, PrState] = {"OPEN": "open", "MERGED": "merged", "CLOSED": "closed"}
_MERGEABLE = {"MERGEABLE": True, "CONFLICTING": False}
# A finished check run's conclusion; anything else (failure, cancelled, timed out, action
# required, startup failure, stale) is a failure.
_CONCLUSIONS: dict[str, CheckState] = {
    "SUCCESS": "success",
    "NEUTRAL": "skipped",
    "SKIPPED": "skipped",
}
# A commit status (the older statuses API).
_STATUS_STATES: dict[str, CheckState] = {
    "SUCCESS": "success",
    "PENDING": "pending",
    "EXPECTED": "pending",
}


class _GhCheck(BaseModel):
    """A CheckRun or a StatusContext from `statusCheckRollup`."""

    model_config = ConfigDict(populate_by_name=True)

    typename: str = Field(default="CheckRun", alias="__typename")
    name: str = ""
    context: str = ""
    status: str = ""
    conclusion: str = ""
    state: str = ""
    details_url: str = Field(default="", alias="detailsUrl")
    target_url: str = Field(default="", alias="targetUrl")


class _GhPr(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    number: int
    url: str
    title: str
    state: str
    mergeable: str = ""
    merge_state: str = Field(default="", alias="mergeStateStatus")
    review_decision: str = Field(default="", alias="reviewDecision")
    head_sha: str = Field(default="", alias="headRefOid")
    created_at: datetime | None = Field(default=None, alias="createdAt")
    checks: list[_GhCheck] | None = Field(default=None, alias="statusCheckRollup")


async def fetch_status(run: CommandRunner, url: str, cwd: Path, now: datetime) -> PrStatus:
    """The pull request at `url`; raises CommandError or OSError when gh fails."""
    output = await run(["gh", "pr", "view", url, "--json", FIELDS], cwd)
    return parse_status(output, now)


def parse_status(output: str, now: datetime) -> PrStatus:
    pr = _GhPr.model_validate_json(output)
    return PrStatus(
        number=pr.number,
        url=pr.url,
        title=pr.title,
        state=_STATES.get(pr.state, "closed"),
        checks=summarize_checks([_check(item) for item in pr.checks or []]),
        mergeable=_MERGEABLE.get(pr.mergeable),
        merge_state=pr.merge_state.lower() or None,
        review_decision=pr.review_decision.lower() or None,
        head_sha=pr.head_sha or None,
        created_at=pr.created_at,
        changed_at=now,
        updated_at=now,
    )


def summarize_checks(items: list[PrCheck]) -> PrChecks:
    passed = sum(item.state in ("success", "skipped") for item in items)
    failed = sum(item.state == "failure" for item in items)
    pending = sum(item.state == "pending" for item in items)
    state: ChecksState = "none"
    if failed:
        state = "failure"
    elif pending:
        state = "pending"
    elif items:
        state = "success"
    return PrChecks(state=state, passed=passed, failed=failed, pending=pending, items=items)


def repo_of(url: str) -> str:
    """`owner/name` of a pull request URL such as https://github.com/owner/name/pull/7."""
    parts = urlparse(url).path.strip("/").split("/")
    return "/".join(parts[:2])


def _check(item: _GhCheck) -> PrCheck:
    if item.typename == "StatusContext":
        state = _STATUS_STATES.get(item.state, "failure")
        return PrCheck(name=item.context, state=state, url=item.target_url or None)
    if item.status != "COMPLETED":
        state = "pending"
    else:
        state = _CONCLUSIONS.get(item.conclusion, "failure")
    return PrCheck(name=item.name, state=state, url=item.details_url or None)
