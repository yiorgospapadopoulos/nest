"""How much of the weekly usage window a chat's engine has used, for the weekly cap."""

from nestd.sessions.models import Session
from nestd.usage.store import UsageStore

_WEEK_MINUTES = 7 * 24 * 60


async def weekly_used(usage: UsageStore, session: Session) -> float | None:
    """In percent; None when the engine has no weekly window, or it was never reported."""
    if session.provider == "claude":
        window = (await usage.limits()).seven_day
        return None if window is None else window.utilization
    if session.provider != "codex":
        return None
    windows = (await usage.engine_limits("codex")).windows
    return next((w.utilization for w in windows if w.minutes == _WEEK_MINUTES), None)
