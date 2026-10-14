from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from nestd.providers.base import TokenUsage, UsageInfo, UsageWindow
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from nestd.usage.store import UsageStore
from tests.fakes import FakeClock
from tests.test_session_store import new_session

HELSINKI = ZoneInfo("Europe/Helsinki")


def tokens(n: int) -> TokenUsage:
    return TokenUsage(
        input_tokens=n,
        output_tokens=2 * n,
        cache_creation_input_tokens=3 * n,
        cache_read_input_tokens=4 * n,
    )


@pytest.fixture
def usage(db: Database, clock: FakeClock) -> UsageStore:
    return UsageStore(db, clock, HELSINKI)


async def test_month_totals_and_days_use_the_local_date(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    one = await sessions.create(new_session())
    two = await sessions.create(new_session(repo="other"))
    # 22:30 UTC on 31 March is 1:30 on 1 April in Helsinki (UTC+3 in summer).
    clock.current = datetime(2026, 3, 31, 22, 30, tzinfo=UTC)
    await usage.record_turn(one.id, tokens(1))
    # 21:30 UTC on 30 April is 0:30 on 1 May in Helsinki: next month.
    clock.current = datetime(2026, 4, 30, 21, 30, tzinfo=UTC)
    await usage.record_turn(one.id, tokens(100))
    clock.current = datetime(2026, 4, 1, 10, 0, tzinfo=UTC)
    await usage.record_turn(two.id, tokens(10))
    await usage.record_turn(one.id, TokenUsage(output_tokens=5))
    clock.current = datetime(2026, 4, 15, 10, 0, tzinfo=UTC)
    await usage.record_turn(two.id, tokens(2))
    # 21:30 UTC on 31 March is still 31 March in Helsinki: previous month.
    clock.current = datetime(2026, 3, 31, 20, 30, tzinfo=UTC)
    await usage.record_turn(two.id, tokens(1000))

    april = await usage.month(2026, 4)

    assert april.sessions == 2
    assert april.tokens.model_dump() == {
        "input_tokens": 13,
        "output_tokens": 31,
        "cache_creation_input_tokens": 39,
        "cache_read_input_tokens": 52,
        "total": 135,
    }
    assert len(april.days) == 30
    assert april.days[0].model_dump() == {"date": date(2026, 4, 1), "tokens": 115, "sessions": 2}
    assert april.days[14].model_dump() == {"date": date(2026, 4, 15), "tokens": 20, "sessions": 1}
    assert sum(day.tokens for day in april.days) == 135
    assert (await usage.month(2026, 5)).tokens.total == 1000
    assert (await usage.month(2026, 3)).days[30].tokens == 10000


async def test_a_month_without_turns(usage: UsageStore) -> None:
    december = await usage.month(2026, 12)

    assert (december.year, december.month, december.sessions) == (2026, 12, 0)
    assert december.tokens.total == 0
    assert [day.date for day in december.days][-1] == date(2026, 12, 31)


async def test_turns_of_deleted_sessions_still_count(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    sessions = SessionStore(db, clock)
    session = await sessions.create(new_session())
    await usage.record_turn(session.id, tokens(1))
    await sessions.delete(session.id)

    assert (await usage.month(2026, 1)).tokens.total == 10


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


async def test_probes_are_counted_apart_from_the_users_sessions(
    usage: UsageStore, db: Database, clock: FakeClock
) -> None:
    session = await SessionStore(db, clock).create(new_session())
    await usage.record_turn(session.id, tokens(1))
    await usage.record_probe(tokens(10))
    await usage.record_probe(TokenUsage(input_tokens=450))
    # Another month in Helsinki: not counted in January.
    clock.current = datetime(2026, 2, 1, 12, tzinfo=UTC)
    await usage.record_probe(tokens(1000))

    january = await usage.month(2026, 1)

    assert (january.sessions, january.tokens.total) == (1, 10)
    assert sum(day.tokens for day in january.days) == 10
    assert january.probes.model_dump() == {"count": 2, "tokens": 550}
    assert (await usage.month(2026, 2)).probes.model_dump() == {"count": 1, "tokens": 10000}


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
