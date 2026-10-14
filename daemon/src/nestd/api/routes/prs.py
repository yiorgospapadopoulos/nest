from typing import Literal

from fastapi import APIRouter, status

from nestd.api.deps import Context, RequireDevice
from nestd.prs.models import MergeRequest, PrListItem
from nestd.sessions.models import SendResult, Session

router = APIRouter(prefix="/api", dependencies=[RequireDevice])


@router.get("/prs")
async def list_prs(
    ctx: Context,
    repo: str | None = None,
    state: Literal["open", "merged", "closed", "all"] = "open",
) -> list[PrListItem]:
    """Pull requests Nest opened, newest first, with their last known status."""
    return await ctx.prs.list_prs(repo, None if state == "all" else state)


@router.post("/sessions/{session_id}/pr/refresh")
async def refresh_pr(session_id: str, ctx: Context) -> Session:
    """Read the session's pull request from GitHub now."""
    return await ctx.prs.refresh(session_id)


@router.post("/sessions/{session_id}/ci-feedback", status_code=status.HTTP_202_ACCEPTED)
async def ci_feedback(session_id: str, ctx: Context) -> SendResult:
    """Send the failing checks' logs (the last lines of each failed GitHub Actions job,
    read with the daemon's gh login) to the agent as a message. 409 `no_failing_checks`
    when none fails now; 502 when GitHub cannot be read.
    """
    return await ctx.prs.send_ci_feedback(session_id)


@router.post("/sessions/{session_id}/merge")
async def merge(session_id: str, ctx: Context, body: MergeRequest | None = None) -> Session:
    """Merge the pull request with gh (squash by default), then close the session and
    remove its worktree. A failed merge returns 502 with gh's stderr and changes nothing.
    """
    return await ctx.prs.merge(session_id, body or MergeRequest())
