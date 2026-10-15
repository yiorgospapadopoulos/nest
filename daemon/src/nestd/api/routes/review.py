from fastapi import APIRouter, status

from nestd.api.deps import Context, RequireDevice
from nestd.review.models import ApproveRequest, FeedbackRequest, SessionDiff
from nestd.sessions.models import Session

router = APIRouter(prefix="/api/sessions", dependencies=[RequireDevice])


@router.get("/{session_id}/diff")
async def diff(session_id: str, ctx: Context) -> SessionDiff:
    """The session's work against its base, untracked files included."""
    return await ctx.reviews.diff(session_id)


@router.post("/{session_id}/approve")
async def approve(session_id: str, body: ApproveRequest, ctx: Context) -> Session:
    """Commit, push and open a pull request; a failed step can be retried."""
    return await ctx.reviews.approve(session_id, body)


@router.post("/{session_id}/feedback", status_code=status.HTTP_202_ACCEPTED)
async def feedback(session_id: str, body: FeedbackRequest, ctx: Context) -> Session:
    """Send a note back into the same session."""
    return await ctx.reviews.feedback(session_id, body.text)
