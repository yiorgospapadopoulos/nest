from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nestd.providers.base import TokenUsage, UsageInfo, UsageWindow
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from nestd.usage.store import UsageStore
from tests.fakes import FakeClock
from tests.test_session_store import new_session

ATHENS = ZoneInfo("Europe/Athens")


def tokens(n: int) -> TokenUsage:
    return TokenUsage(
        input_tokens=n,
        output_tokens=2 * n,
        cache_creation_input_tokens=3 * n,
        cache_read_input_tokens=4 * n,
    )


@pytest.fixture
def usage(db: Database, clock: FakeClock) -> UsageStore:
    return UsageStore(db, clock, ATHENS)


async def test_a_month_by_the_local_calendar(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    one = await sessions.create(new_session())
    two = await sessions.create(new_session(repo="other"))
    pixie_a = await sessions.create(new_session(repo="pixie:a"))
    pixie_b = await sessions.create(new_session(repo="pixie:b"))
    idle = await sessions.create(new_session(repo="idle"))
    # 22:30 UTC on 31 March is 1:30 on 1 April in Athens (UTC+3 in summer).
    clock.current = datetime(2026, 3, 31, 22, 30, tzinfo=UTC)
    await usage.record_turn(one.id, tokens(1))
    # 21:30 UTC on 30 April is 0:30 on 1 May in Athens: next month.
    clock.current = datetime(2026, 4, 30, 21, 30, tzinfo=UTC)
    await usage.record_turn(one.id, tokens(100))
    clock.current = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    await usage.record_turn(two.id, tokens(10))
    await usage.record_turn(one.id, TokenUsage(output_tokens=5))
    clock.current = datetime(2026, 4, 15, 10, 0, tzinfo=UTC)
    await usage.record_turn(two.id, tokens(2))
    await usage.record_subagent(one.id, "msg_1", tokens(3))
    clock.current = datetime(2026, 4, 20, 10, 0, tzinfo=UTC)
    await usage.record_turn(pixie_a.id, tokens(4))
    await usage.record_turn(pixie_b.id, tokens(4))
    await usage.record_turn(idle.id, TokenUsage())
    # 20:30 UTC on 31 March is still 31 March in Athens: previous month.
    clock.current = datetime(2026, 3, 31, 20, 30, tzinfo=UTC)
    await usage.record_turn(two.id, tokens(1000))
    clock.current = datetime(2026, 4, 10, 12, 0, tzinfo=UTC)

    april = await usage.period("month", date(2026, 4, 9))

    assert (april.unit, april.start, april.end) == ("month", date(2026, 4, 1), date(2026, 4, 30))
    assert april.current
    assert april.sessions == 5
    assert april.tokens.model_dump() == {
        "input_tokens": 24,
        "output_tokens": 53,
        "cache_creation_input_tokens": 72,
        "cache_read_input_tokens": 96,
        "total": 245,
    }
    assert april.subagents.model_dump() == {
        "input_tokens": 3,
        "output_tokens": 6,
        "cache_creation_input_tokens": 9,
        "cache_read_input_tokens": 12,
        "total": 30,
    }
    assert len(april.bars) == 30
    assert april.bars[0].model_dump(mode="json") == {
        "start": "2026-04-01T00:00:00+03:00",
        "tokens": 115,
        "sessions": 2,
    }
    assert (april.bars[14].tokens, april.bars[14].sessions) == (50, 2)
    # The idle chat counts as a chat on its day, with no tokens.
    assert (april.bars[19].tokens, april.bars[19].sessions) == (80, 3)
    assert sum(bar.tokens for bar in april.bars) == 245
    assert [project.model_dump() for project in april.projects] == [
        {"name": "other", "tokens": 120, "pixies": False},
        {"name": "Pixies", "tokens": 80, "pixies": True},
        {"name": "repo", "tokens": 45, "pixies": False},
    ]
    may = await usage.period("month", date(2026, 5, 31))
    assert (may.tokens.total, may.current) == (1000, False)
    assert (await usage.period("month", date(2026, 3, 1))).bars[30].tokens == 10000


async def test_a_subagent_reply_counts_once_with_its_largest_tokens(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    one = await sessions.create(new_session())
    two = await sessions.create(new_session())
    first = clock.now()
    await usage.record_subagent(one.id, "msg_1", tokens(1))
    clock.advance(timedelta(seconds=30))
    await usage.record_subagent(one.id, "msg_1", tokens(2))
    # A later message of the reply can only raise a count.
    await usage.record_subagent(one.id, "msg_1", TokenUsage(input_tokens=1, output_tokens=9))
    await usage.record_subagent(two.id, "msg_1", tokens(5))
    await usage.record_subagent("gone", "msg_2", tokens(7))
    await usage.record_turn(one.id, tokens(10))
    await usage.record_turn(one.id, tokens(10))

    rows = await db.fetch_all(
        "SELECT session_id, message_id, subagent, ts, input_tokens, output_tokens"
        " FROM turn_usage ORDER BY id"
    )
    day = await usage.period("day", first.date())

    assert [tuple(row) for row in rows] == [
        (one.id, "msg_1", 1, first.isoformat(), 2, 9),
        (two.id, "msg_1", 1, clock.now().isoformat(), 5, 10),
        (one.id, None, 0, clock.now().isoformat(), 10, 20),
        (one.id, None, 0, clock.now().isoformat(), 10, 20),
    ]
    assert (day.tokens.total, day.subagents.total, day.sessions) == (275, 75, 2)


async def test_a_day_has_an_hour_a_bar(usage: UsageStore, db: Database, clock: FakeClock) -> None:
    session = await SessionStore(db, clock).create(new_session())
    for moment in (
        datetime(2026, 4, 14, 20, 59, tzinfo=UTC),  # 23:59 on 14 April in Athens
        datetime(2026, 4, 15, 6, 30, tzinfo=UTC),  # 9:30
        datetime(2026, 4, 15, 20, 59, tzinfo=UTC),  # 23:59
        datetime(2026, 4, 15, 21, 0, tzinfo=UTC),  # midnight: 16 April
    ):
        clock.current = moment
        await usage.record_turn(session.id, tokens(1))

    day = await usage.period("day", date(2026, 4, 15))

    assert (day.start, day.end, day.current) == (date(2026, 4, 15), date(2026, 4, 15), False)
    assert len(day.bars) == 24
    assert day.bars[0].start == datetime(2026, 4, 15, tzinfo=ATHENS)
    assert day.bars[23].start == datetime(2026, 4, 15, 23, tzinfo=ATHENS)
    assert [(bar.tokens, bar.sessions) for bar in day.bars if bar.tokens] == [(10, 1), (10, 1)]
    assert (day.bars[9].tokens, day.bars[23].tokens) == (10, 10)
    assert (await usage.period("day", date(2026, 4, 16))).current


async def test_a_week_starts_on_monday_across_a_clock_change(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    session = await SessionStore(db, clock).create(new_session())
    for moment in (
        datetime(2026, 10, 18, 20, 59, tzinfo=UTC),  # 23:59 on Sunday 18 October in Athens
        datetime(2026, 10, 18, 21, 0, tzinfo=UTC),  # midnight: Monday 19 October
        # Athens is UTC+2 from 25 October.
        datetime(2026, 10, 25, 21, 30, tzinfo=UTC),  # 23:30 on Sunday 25 October
        datetime(2026, 10, 25, 22, 30, tzinfo=UTC),  # 0:30 on Monday 26 October
    ):
        clock.current = moment
        await usage.record_turn(session.id, tokens(1))
    clock.current = datetime(2026, 10, 17, 12, tzinfo=UTC)

    week = await usage.period("week", date(2026, 10, 22))

    assert (week.start, week.end, week.current) == (date(2026, 10, 19), date(2026, 10, 25), False)
    assert [bar.model_dump(mode="json")["start"] for bar in week.bars] == [
        "2026-10-19T00:00:00+03:00",
        "2026-10-20T00:00:00+03:00",
        "2026-10-21T00:00:00+03:00",
        "2026-10-22T00:00:00+03:00",
        "2026-10-23T00:00:00+03:00",
        "2026-10-24T00:00:00+03:00",
        "2026-10-25T00:00:00+03:00",
    ]
    assert [bar.tokens for bar in week.bars] == [10, 0, 0, 0, 0, 0, 10]
    this_week = await usage.period("week", date(2026, 10, 12))
    assert (this_week.start, this_week.end) == (date(2026, 10, 12), date(2026, 10, 18))
    assert (this_week.current, this_week.tokens.total) == (True, 10)


async def test_a_year_has_a_month_a_bar(usage: UsageStore, db: Database, clock: FakeClock) -> None:
    session = await SessionStore(db, clock).create(new_session())
    for moment in (
        datetime(2025, 1, 15, 10, tzinfo=UTC),
        datetime(2025, 12, 31, 21, 30, tzinfo=UTC),  # 23:30 on 31 December in Athens
        datetime(2025, 12, 31, 22, 30, tzinfo=UTC),  # 0:30 on 1 January 2026
    ):
        clock.current = moment
        await usage.record_turn(session.id, tokens(1))

    year = await usage.period("year", date(2025, 6, 10))

    assert (year.start, year.end, year.current) == (date(2025, 1, 1), date(2025, 12, 31), False)
    assert [bar.start for bar in year.bars] == [
        datetime(2025, month, 1, tzinfo=ATHENS) for month in range(1, 13)
    ]
    assert [bar.tokens for bar in year.bars] == [10, *[0] * 10, 10]
    assert (await usage.period("year", date(2026, 1, 1))).current


async def test_an_empty_period(usage: UsageStore) -> None:
    december = await usage.period("month", date(2026, 12, 25))

    assert (december.sessions, december.tokens.total, december.subagents.total) == (0, 0, 0)
    assert (december.projects, december.probes.count) == ([], 0)
    assert [bar.tokens for bar in december.bars] == [0] * 31


async def test_turns_of_deleted_sessions_still_count(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    session = await sessions.create(new_session())
    await usage.record_turn(session.id, tokens(1))
    await usage.record_subagent(session.id, "msg_1", tokens(1))
    await sessions.delete(session.id)

    january = await usage.period("month", date(2026, 1, 1))

    assert (january.tokens.total, january.subagents.total) == (20, 10)
    assert january.projects[0].model_dump() == {"name": "repo", "tokens": 20, "pixies": False}


async def test_limits_keep_the_latest_of_each_window(usage: UsageStore, clock: FakeClock) -> None:
    resets = datetime(2026, 1, 1, 17, tzinfo=UTC)
    assert (await usage.limits()).model_dump() == {"five_hour": None, "seven_day": None}

    await usage.update_limits(
        UsageInfo(
            five_hour=UsageWindow(utilization=0.2, resets_at=resets),
            seven_day=UsageWindow(utilization=0.5, resets_at=None),
        )
    )
    clock.advance(timedelta(minutes=5))
    await usage.update_limits(
        UsageInfo(five_hour=UsageWindow(utilization=0.3, resets_at=resets), seven_day=None)
    )
    limits = await usage.limits()

    assert limits.five_hour is not None
    assert (limits.five_hour.utilization, limits.five_hour.resets_at) == (0.3, resets)
    assert limits.five_hour.updated_at == clock.now()
    assert limits.seven_day is not None
    assert (limits.seven_day.utilization, limits.seven_day.resets_at) == (0.5, None)
    assert limits.seven_day.updated_at == clock.now() - timedelta(minutes=5)


async def test_page_asks_are_counted_apart_like_probes(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    session = await SessionStore(db, clock).create(new_session())
    await usage.record_turn(session.id, tokens(1))
    await usage.record_ask(tokens(10))
    await usage.record_probe(tokens(5))
    clock.current = datetime(2026, 2, 1, 12, tzinfo=UTC)
    await usage.record_ask(tokens(1000))

    january = await usage.period("month", date(2026, 1, 1))

    assert (january.sessions, january.tokens.total) == (1, 10)
    assert january.asks.model_dump() == {"count": 1, "tokens": 100}
    assert january.probes.model_dump() == {"count": 1, "tokens": 50}
    assert (await usage.period("month", date(2026, 2, 1))).asks.count == 1
    assert (await usage.period("day", date(2026, 1, 2))).asks.count == 0


async def test_probes_are_counted_apart_from_the_users_sessions(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    session = await SessionStore(db, clock).create(new_session())
    await usage.record_turn(session.id, tokens(1))
    await usage.record_probe(tokens(10))
    await usage.record_probe(TokenUsage(input_tokens=450))
    # Another month in Athens: not counted in January.
    clock.current = datetime(2026, 2, 1, 12, tzinfo=UTC)
    await usage.record_probe(tokens(1000))

    january = await usage.period("month", date(2026, 1, 1))

    assert (january.sessions, january.tokens.total) == (1, 10)
    assert sum(bar.tokens for bar in january.bars) == 10
    assert january.probes.model_dump() == {"count": 2, "tokens": 550}
    february = await usage.period("month", date(2026, 2, 1))
    assert february.probes.model_dump() == {"count": 1, "tokens": 10000}
    assert (await usage.period("day", date(2026, 1, 2))).probes.count == 0


async def test_limits_updated_at_is_the_latest_window_report(
    usage: UsageStore, clock: FakeClock
) -> None:
    assert await usage.limits_updated_at() is None

    await usage.update_limits(
        UsageInfo(five_hour=None, seven_day=UsageWindow(utilization=0.1, resets_at=None))
    )
    first = clock.now()
    clock.advance(timedelta(minutes=2))
    await usage.update_limits(
        UsageInfo(five_hour=UsageWindow(utilization=0.2, resets_at=None), seven_day=None)
    )

    assert await usage.limits_updated_at() == first + timedelta(minutes=2)
