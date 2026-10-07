"""Which notifications the user's settings let through at a given local time."""

from datetime import time

from harness.config.models import NotificationSettings, QuietHours


def should_send(settings: NotificationSettings, kind: str, now: time) -> bool:
    enabled: bool = getattr(settings.kinds, kind)
    return enabled and not in_quiet_hours(settings.quiet_hours, now)


def in_quiet_hours(quiet: QuietHours | None, now: time) -> bool:
    if quiet is None:
        return False
    start, end = time.fromisoformat(quiet.start), time.fromisoformat(quiet.end)
    if start < end:
        return start <= now < end
    # Wraps past midnight, such as 22:00 to 07:00.
    return now >= start or now < end
