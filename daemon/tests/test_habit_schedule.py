"""When a habit's schedule is due, in the Mac's local time, across clock changes (B42)."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from pydantic import TypeAdapter

from nestd.pixies.habit_models import Schedule
from nestd.pixies.schedule import describe, latest_due, next_due

NEW_YORK = ZoneInfo("America/New_York")
SCHEDULE: TypeAdapter[Schedule] = TypeAdapter(Schedule)


def schedule(**fields: object) -> Schedule:
    return SCHEDULE.validate_python(fields)


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)  # pyright: ignore[reportArgumentType]


@pytest.mark.parametrize(
    ("fields", "after", "due"),
    [
        # 07:00 in New York: 09:00 is later that day.
        ({"kind": "daily", "time": "09:00"}, utc(2026, 1, 1, 12), utc(2026, 1, 1, 14)),
        # Exactly at an occurrence: the next one.
        ({"kind": "daily", "time": "09:00"}, utc(2026, 1, 1, 14), utc(2026, 1, 2, 14)),
        ({"kind": "hourly", "minute": 15}, utc(2026, 1, 1, 12, 20), utc(2026, 1, 1, 13, 15)),
        ({"kind": "hourly", "minute": 15}, utc(2026, 1, 1, 12, 10), utc(2026, 1, 1, 12, 15)),
        # Friday 2 January after 09:00: Monday.
        ({"kind": "weekdays", "time": "09:00"}, utc(2026, 1, 2, 15), utc(2026, 1, 5, 14)),
        # Saturday: Monday.
        ({"kind": "weekdays", "time": "09:00"}, utc(2026, 1, 3, 10), utc(2026, 1, 5, 14)),
        # Wednesdays at 18:30, from Thursday 1 January: Wednesday 7 January.
        (
            {"kind": "weekly", "weekday": 2, "time": "18:30"},
            utc(2026, 1, 1, 12),
            utc(2026, 1, 7, 23, 30),
        ),
        # Thursdays from a Thursday morning: the same day.
        (
            {"kind": "weekly", "weekday": 3, "time": "18:30"},
            utc(2026, 1, 1, 12),
            utc(2026, 1, 1, 23, 30),
        ),
    ],
)
def test_next_due_per_kind(fields: dict[str, object], after: datetime, due: datetime) -> None:
    assert next_due(schedule(**fields), after, NEW_YORK) == due


def test_a_time_the_clock_skips_runs_at_the_next_valid_minute() -> None:
    # 8 March 2026: 02:00 EST jumps to 03:00 EDT, so 02:30 never happens.
    daily = schedule(kind="daily", time="02:30")

    first = next_due(daily, utc(2026, 3, 8, 0), NEW_YORK)
    second = next_due(daily, first, NEW_YORK)

    assert first == utc(2026, 3, 8, 7)  # 03:00 EDT
    assert second == utc(2026, 3, 9, 6, 30)  # 02:30 EDT


def test_a_time_the_clock_repeats_runs_once() -> None:
    # 1 November 2026: 02:00 EDT falls back to 01:00 EST, so 01:30 happens twice.
    daily = schedule(kind="daily", time="01:30")

    first = next_due(daily, utc(2026, 11, 1, 0), NEW_YORK)
    second = next_due(daily, first, NEW_YORK)

    assert first == utc(2026, 11, 1, 5, 30)  # 01:30 EDT, the first time
    assert second == utc(2026, 11, 2, 6, 30)  # the next day, not 01:30 EST


def test_hourly_across_both_clock_changes() -> None:
    hourly = schedule(kind="hourly", minute=30)

    def run(after: datetime, count: int) -> list[datetime]:
        times: list[datetime] = []
        for _ in range(count):
            after = next_due(hourly, after, NEW_YORK)
            times.append(after)
        return times

    spring = run(utc(2026, 3, 8, 6), 3)
    autumn = run(utc(2026, 11, 1, 5), 3)

    # 01:30 EST, 02:30 (skipped) at 03:00 EDT, 03:30 EDT.
    assert spring == [utc(2026, 3, 8, 6, 30), utc(2026, 3, 8, 7), utc(2026, 3, 8, 7, 30)]
    # 01:30 EDT, then 02:30 EST: the repeated 01:30 EST runs no second time.
    assert autumn == [utc(2026, 11, 1, 5, 30), utc(2026, 11, 1, 7, 30), utc(2026, 11, 1, 8, 30)]


def test_on_the_hour_a_skipped_time_and_the_next_one_run_once() -> None:
    hourly = schedule(kind="hourly", minute=0)

    first = next_due(hourly, utc(2026, 3, 8, 6, 30), NEW_YORK)
    second = next_due(hourly, first, NEW_YORK)

    # 02:00 does not exist and moves to 03:00 EDT, which is also 03:00's own time.
    assert first == utc(2026, 3, 8, 7)
    assert second == utc(2026, 3, 8, 8)


def test_the_systems_own_zone_by_default() -> None:
    after = datetime.now(UTC)

    due = next_due(schedule(kind="daily", time="09:15"), after, None)

    local = due.astimezone()
    assert (local.hour, local.minute) == (9, 15)
    assert after < due <= after + timedelta(days=1, hours=2)


def test_latest_due_is_the_newest_time_since() -> None:
    hourly = schedule(kind="hourly", minute=0)
    daily = schedule(kind="daily", time="09:00")

    newest = latest_due(hourly, utc(2026, 1, 1), utc(2026, 1, 3, 10, 30), NEW_YORK)
    none_yet = latest_due(daily, utc(2026, 1, 1, 14), utc(2026, 1, 2, 13), NEW_YORK)
    exactly = latest_due(daily, utc(2026, 1, 1, 14), utc(2026, 1, 2, 14), NEW_YORK)
    # Weeks away: only the newest time is looked for.
    long_ago = latest_due(daily, utc(2025, 1, 1), utc(2026, 1, 2, 15), NEW_YORK)

    assert newest == utc(2026, 1, 3, 10)
    assert none_yet is None
    assert exactly == utc(2026, 1, 2, 14)
    assert long_ago == utc(2026, 1, 2, 14)


@pytest.mark.parametrize(
    ("fields", "words"),
    [
        ({"kind": "hourly", "minute": 15}, "Every hour at :15"),
        ({"kind": "hourly", "minute": 0}, "Every hour at :00"),
        ({"kind": "daily", "time": "09:00"}, "Daily at 09:00"),
        ({"kind": "weekdays", "time": "09:00"}, "Weekdays at 09:00"),
        ({"kind": "weekly", "weekday": 0, "time": "08:30"}, "Mondays at 08:30"),
        ({"kind": "weekly", "weekday": 6, "time": "20:00"}, "Sundays at 20:00"),
    ],
)
def test_describe(fields: dict[str, object], words: str) -> None:
    assert describe(schedule(**fields)) == words
