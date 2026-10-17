"""A usage window reaching `[usage] warn_percent` is announced once per period (D104)."""

import json
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import pytest

from nestd.config.models import UsageSettings
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.notifications.messages import Notice
from nestd.providers.base import UsageInfo, UsageWindow
from nestd.storage.db import Database
from nestd.usage.warnings import UsageWarnings
from tests.async_support import until
from tests.fakes import START, FakeClock
from tests.test_notification_delivery import FlakyBus

RESET = START + timedelta(hours=3)


class Rig:
    def __init__(self, db: Database, clock: FakeClock) -> None:
        self.db = db
        self.bus = EventBus(db, clock)
        self.settings = UsageSettings()
        self.pushed: list[Notice] = []
        self.warnings = self.build()

    def build(self) -> UsageWarnings:
        return UsageWarnings(
            bus=self.bus, db=self.db, settings=lambda: self.settings, push=self.push
        )

    async def push(self, notice: Notice) -> None:
        self.pushed.append(notice)

    async def warned(self) -> list[dict[str, object]]:
        rows = await self.db.fetch_all(
            "SELECT payload FROM events WHERE type = ? ORDER BY id", (types.USAGE_WARNING,)
        )
        return [json.loads(row["payload"]) for row in rows]


@pytest.fixture
async def rig(db: Database, clock: FakeClock) -> AsyncIterator[Rig]:
    result = Rig(db, clock)
    yield result
    await result.warnings.stop()


def info(
    five: float | None = None,
    week: float | None = None,
    five_reset: datetime | None = RESET,
    week_reset: datetime | None = None,
) -> UsageInfo:
    return UsageInfo(
        five_hour=None if five is None else UsageWindow(utilization=five, resets_at=five_reset),
        seven_day=None if week is None else UsageWindow(utilization=week, resets_at=week_reset),
    )


async def test_warns_once_when_a_window_reaches_the_level(rig: Rig) -> None:
    await rig.warnings.check(info(five=0.79))
    assert await rig.warned() == []

    await rig.warnings.check(info(five=0.8))
    await rig.warnings.check(info(five=0.85))
    # The same period, reported a little differently.
    await rig.warnings.check(info(five=0.9, five_reset=RESET + timedelta(seconds=30)))

    assert await rig.warned() == [
        {"window": "five_hour", "utilization": 0.8, "resets_at": RESET.isoformat()}
    ]
    assert [(n.kind, n.title, n.body, n.url, n.tag) for n in rig.pushed] == [
        (
            "usage_warning",
            "Usage warning",
            "The 5-hour usage limit is 80% used.",
            "/settings/agents",
            "usage-warning-five_hour",
        )
    ]


async def test_a_new_period_warns_again_and_windows_are_apart(rig: Rig) -> None:
    await rig.warnings.check(info(five=0.95, week=0.97))
    later = RESET + timedelta(hours=5)
    await rig.warnings.check(info(five=0.96, week=0.98, five_reset=later))

    assert [(w["window"], w["resets_at"]) for w in await rig.warned()] == [
        ("five_hour", RESET.isoformat()),
        ("seven_day", None),
        ("five_hour", later.isoformat()),
    ]


async def test_a_window_with_and_without_a_reset_time_are_different_periods(rig: Rig) -> None:
    await rig.warnings.check(info(five=0.9, five_reset=None))
    await rig.warnings.check(info(five=0.9))
    await rig.warnings.check(info(five=0.9, five_reset=None))

    assert len(await rig.warned()) == 3


async def test_off_or_without_a_notification(rig: Rig) -> None:
    rig.settings = UsageSettings(warn_percent=None)
    await rig.warnings.check(info(five=0.99))
    assert await rig.warned() == []

    rig.settings = UsageSettings(warn_percent=90, warn_notify=False)
    await rig.warnings.check(info(five=0.89))
    await rig.warnings.check(info(five=0.9))

    assert len(await rig.warned()) == 1
    assert rig.pushed == []


async def test_a_restarted_daemon_remembers_what_it_warned_about(rig: Rig) -> None:
    await rig.warnings.check(info(five=0.9))
    restarted = rig.build()

    await restarted.check(info(five=0.95))

    assert len(await rig.warned()) == 1


async def test_follows_usage_updates_on_the_bus(rig: Rig) -> None:
    await rig.bus.publish(types.USAGE_UPDATED, info(five=0.99).model_dump(mode="json"))
    await rig.warnings.start()
    await rig.bus.publish(types.SESSION_STATE, {"state": "idle"}, "s1")
    await rig.bus.publish(types.USAGE_UPDATED, {"five_hour": "nonsense"})
    await rig.bus.publish(
        types.USAGE_UPDATED, info(week=0.9, week_reset=RESET).model_dump(mode="json")
    )

    async def warned() -> bool:
        return len(await rig.warned()) == 1

    await until(warned)
    assert (await rig.warned())[0]["window"] == "seven_day"


async def test_a_failed_check_is_logged(rig: Rig, caplog: pytest.LogCaptureFixture) -> None:
    async def broken(notice: Notice) -> None:
        raise RuntimeError("push service down")

    rig.warnings = UsageWarnings(bus=rig.bus, db=rig.db, settings=lambda: rig.settings, push=broken)
    await rig.warnings.start()
    await rig.bus.publish(types.USAGE_UPDATED, info(five=0.9).model_dump(mode="json"))
    await rig.bus.publish(types.USAGE_UPDATED, info(week=0.9).model_dump(mode="json"))

    async def both() -> bool:
        return len(await rig.warned()) == 2

    await until(both)
    assert "usage warning failed (RuntimeError)" in caplog.text


async def test_a_follower_that_fell_behind_subscribes_again(db: Database, clock: FakeClock) -> None:
    rig = Rig(db, clock)
    rig.bus = FlakyBus(db, clock)
    rig.warnings = rig.build()
    await rig.warnings.start()
    await rig.bus.publish(types.USAGE_UPDATED, info(five=0.9).model_dump(mode="json"))

    async def warned() -> bool:
        return len(await rig.warned()) == 1

    try:
        await until(warned)
    finally:
        await rig.warnings.stop()
