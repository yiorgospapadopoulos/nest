from fastapi import APIRouter

from harness.api.deps import Context, RequireDevice
from harness.approvals.models import Approval, ApprovalStatus
from harness.approvals.resolutions import ResolveApproval, resolution_for

router = APIRouter(prefix="/api/approvals", dependencies=[RequireDevice])


@router.get("")
async def list_approvals(
    ctx: Context, status: ApprovalStatus | None = None, project: str | None = None
) -> list[Approval]:
    """Oldest first; `project` is a repo name."""
    return await ctx.approvals.list_approvals(status, project)


@router.get("/{approval_id}")
async def get_approval(approval_id: str, ctx: Context) -> Approval:
    return await ctx.approvals.get(approval_id)


@router.post("/{approval_id}/resolve")
async def resolve_approval(approval_id: str, body: ResolveApproval, ctx: Context) -> Approval:
    """Permissions, questions and plans; reviews use the session's approve, reject and
    feedback. A plan approved in Auto mode needs a model that supports it (422).
    """
    approval = await ctx.approvals.get(approval_id)
    resolution = resolution_for(approval, body)
    if body.mode is not None:
        session = await ctx.sessions.get(approval.session_id)
        await ctx.engine.require_mode(session.model, body.mode)
    return await ctx.approvals.resolve(approval_id, resolution)
