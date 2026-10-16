"""What a project's chats are working towards (D092)."""

from fastapi import APIRouter

from nestd.api.deps import Context, RequireDevice
from nestd.api.schemas import Goal
from nestd.sessions.models import IN_FLIGHT

router = APIRouter(prefix="/api/goals", dependencies=[RequireDevice])


@router.get("")
async def list_goals(ctx: Context, repo: str | None = None) -> list[Goal]:
    """Of the chats the chat list shows, each one working or with tasks left in its visible
    list (deleted ones aside): working chats first, then the most recently updated.
    """
    goals: list[tuple[bool, Goal]] = []
    sessions = await ctx.sessions.list_sessions(repo)
    for session in sorted(sessions, key=lambda s: s.updated_at, reverse=True):
        tasks = (await ctx.tracking.snapshot(session.id)).tasks
        working = session.state in IN_FLIGHT
        if working or any(task.status != "deleted" for task in tasks):
            goals.append((working, Goal(session_id=session.id, tasks=tasks)))
    return [goal for _, goal in sorted(goals, key=lambda g: not g[0])]
