from typing import Literal

from fastapi import APIRouter

from harness.api.deps import Context, RequireDevice
from harness.prs.models import MergeRequest, PrListItem
from harness.sessions.models import Session

router = APIRouter(prefix="/api", dependencies=[RequireDevice])


@router.get("/prs")
async def list_prs(
    ctx: Context,
    repo: str | None = None,
    state: Literal["open", "merged", "closed", "all"] = "open",
) -> list[PrListItem]:
    """Pull requests harness opened, newest first, with their last known status."""
    return await ctx.prs.list_prs(repo, None if state == "all" else state)


@router.post("/sessions/{session_id}/pr/refresh")
async def refresh_pr(session_id: str, ctx: Context) -> Session:
    """Read the session's pull request from GitHub now."""
    return await ctx.prs.refresh(session_id)


@router.post("/sessions/{session_id}/merge")
async def merge(session_id: str, ctx: Context, body: MergeRequest | None = None) -> Session:
    """Merge the pull request with gh (squash by default), then close the session and
    remove its worktree. A failed merge returns 502 with gh's stderr and changes nothing.
    """
    return await ctx.prs.merge(session_id, body or MergeRequest())
