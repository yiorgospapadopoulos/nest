"""When a habit's schedule is due (B42). Schedules name wall times in the Mac's local zone:
a wall time the clock skips that day runs at the next minute that exists, and one the
clock repeats runs once, the first time.
"""

from datetime import UTC, date, datetime, time, timedelta, tzinfo

from nestd.pixies.habit_models import Daily, Hourly, Schedule, Weekdays, Weekly

# Every kind is due at least once in this many days.
_LONGEST = timedelta(days=8)
_MINUTE = timedelta(minutes=1)
_SATURDAY = 5
_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def next_due(schedule: Schedule, after: datetime, zone: tzinfo | None) -> datetime:
    """The first time the schedule is due strictly after `after` (UTC). `zone` None is the
    system's own zone.
    """
    day = _wall(after, zone).date() - timedelta(days=1)
    while True:
        for wall in _times(schedule, day):
            due = _instant(datetime.combine(day, wall), zone)
            # Walls in order give times in order: a skipped one moves to the next that
            # exists, which is never later than the next wall's own time.
            if due > after:
                return due
        day += timedelta(days=1)


def latest_due(
    schedule: Schedule, since: datetime, now: datetime, zone: tzinfo | None
) -> datetime | None:
    """The newest time the schedule was due after `since` and at or before `now`; older
    ones are of no use, since only the newest of them may still run.
    """
    after = max(since, now - _LONGEST)
    latest: datetime | None = None
    while (due := next_due(schedule, after, zone)) <= now:
        latest = after = due
    return latest


def describe(schedule: Schedule) -> str:
    """The schedule in words, such as "Weekdays at 09:00"."""
    if isinstance(schedule, Hourly):
        return f"Every hour at :{schedule.minute:02d}"
    if isinstance(schedule, Daily):
        return f"Daily at {schedule.time}"
    if isinstance(schedule, Weekdays):
        return f"Weekdays at {schedule.time}"
    return f"{_DAY_NAMES[schedule.weekday]}s at {schedule.time}"


def _times(schedule: Schedule, day: date) -> list[time]:
    """The wall times the schedule names on `day`, in order."""
    if isinstance(schedule, Hourly):
        return [time(hour, schedule.minute) for hour in range(24)]
    on_day = (
        isinstance(schedule, Daily)
        or (isinstance(schedule, Weekdays) and day.weekday() < _SATURDAY)
        or (isinstance(schedule, Weekly) and day.weekday() == schedule.weekday)
    )
    return [time.fromisoformat(schedule.time)] if on_day else []


def _instant(wall: datetime, zone: tzinfo | None) -> datetime:
    """The UTC time of a naive local wall time: the next one that exists when the clock
    skips it, the first one when it repeats it (fold 0).
    """
    while _wall(at := _aware(wall, zone), zone) != wall:
        wall += _MINUTE
    return at.astimezone(UTC)


def _aware(wall: datetime, zone: tzinfo | None) -> datetime:
    # A naive time's astimezone() reads it in the system's zone, clock changes included.
    return wall.astimezone() if zone is None else wall.replace(tzinfo=zone)


def _wall(moment: datetime, zone: tzinfo | None) -> datetime:
    return moment.astimezone(UTC).astimezone(zone).replace(tzinfo=None)
