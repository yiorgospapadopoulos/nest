from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, ConfigDict

from nestd.api.deps import Context, RequireDevice
from nestd.prs.models import AutoMergeRequest, MergeRequest, PrListItem
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


class ReviewFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The review comments to send, by id; null sends every one that waits.
    ids: list[str] | None = None


@router.post("/sessions/{session_id}/pr/review-feedback", status_code=status.HTTP_202_ACCEPTED)
async def review_feedback(
    session_id: str, ctx: Context, body: ReviewFeedback | None = None
) -> SendResult:
    """Send the pull request's review comments that wait (read with the daemon's gh login)
    to the agent as a message, and mark them sent: all of them, or those whose id is in
    `ids` (others are ignored). 409 `no_review_comments` when none of them waits; 502 when
    GitHub cannot be read.
    """
    return await ctx.prs.send_review_feedback(session_id, None if body is None else body.ids)


class ReviewSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # New review comments go to the agent as they arrive, instead of waiting in Needs you.
    auto_send: bool


@router.patch("/sessions/{session_id}/pr/review")
async def review_settings(session_id: str, body: ReviewSettings, ctx: Context) -> Session:
    return await ctx.prs.set_review_auto_send(session_id, body.auto_send)


@router.post("/sessions/{session_id}/merge")
async def merge(session_id: str, ctx: Context, body: MergeRequest | None = None) -> Session:
    """Merge the pull request with gh (squash by default). A movable chat stays open with its
    worktree; any other session closes and its worktree is removed. A failed merge returns
    502 with gh's stderr and changes nothing.
    """
    return await ctx.prs.merge(session_id, body or MergeRequest())


@router.patch("/sessions/{session_id}/pr/auto-merge")
async def auto_merge(session_id: str, body: AutoMergeRequest, ctx: Context) -> Session:
    """Merge the pull request once its checks pass (`enabled`), or stop waiting. One that is
    ready now is merged now, with merge's errors. GitHub's own auto-merge is used when GitHub
    waits for required checks or reviews; otherwise Nest merges when it sees the pull request
    ready. 502 when gh cannot turn GitHub's auto-merge off.
    """
    return await ctx.prs.set_auto_merge(session_id, body)


@router.post("/sessions/{session_id}/restack")
async def restack(session_id: str, ctx: Context) -> Session:
    """Move a stacked chat's branch onto its new base after the pull request under it merged:
    rebase it when Nest could not by itself, then for an open pull request force-push it
    (only while GitHub has what Nest last read there) and point the pull request at the new
    base. 409 `restack_failed` with the reason when the rebase cannot happen, such as
    conflicts or uncommitted changes; 409 when nothing waits or the branch under it moves
    first; 502 when git or gh fails.
    """
    return await ctx.stacks.restack(session_id)


@router.post("/sessions/{session_id}/pr/guide", status_code=status.HTTP_202_ACCEPTED)
async def write_guide(session_id: str, ctx: Context) -> Session:
    """Start writing a review guide for the pull request: one call on the chat's engine and
    model, from the pull request's diff only, with no tools. The session's `pr_guide` reads
    `writing`, then `ready` with its markdown artifact (a new version when written again) or
    `failed` with the reason, published as `session.updated`. 409 while one is written.
    """
    return await ctx.guides.write(session_id)


@router.post("/sessions/{session_id}/pr/guide/post")
async def post_guide(session_id: str, ctx: Context) -> Session:
    """Post the review guide, as its artifact reads now, on the pull request as a comment.
    409 before a guide is ready; 502 when gh fails.
    """
    return await ctx.guides.post(session_id)
