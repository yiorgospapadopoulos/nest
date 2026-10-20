import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import EngineWindow, UsageInfo, UsageWindow
from nestd.storage.db import Database
from nestd.usage.models import EngineLimits
from nestd.usage.probe import UsageProbe
from nestd.usage.refresher import (
    FORCED_SPACING,
    IDLE_CLOSE,
    ProbeFailedError,
    RefreshTooSoonError,
    UsageRefresher,
)
from nestd.usage.store import UsageStore
from nestd.usage.visibility import VISIBILITY_TTL, ClientVisibility
from tests.fake_probe import FakeProbeFactory, answer, result
from tests.fakes import FakeClock

INTERVAL = timedelta(minutes=3)


class Setting:
    """The refresh interval as the settings file has it; None is off."""

    def __init__(self) -> None:
        self.interval: timedelta | None = INTERVAL

    def __call__(self) -> timedelta | None:
        return self.interval


class FakeCodex:
    """Codex's usage reader: the next scripted windows, or None (signed out, no answer)."""

    def __init__(self) -> None:
        self.replies: list[UsageInfo | None] = []
        self.calls = 0

    async def __call__(self) -> UsageInfo | None:
        self.calls += 1
        return self.replies.pop(0) if self.replies else None


def codex_info(used: float = 0.3) -> UsageInfo:
    """Codex's free plan: one 30-day window."""
    window = EngineWindow(utilization=used, resets_at=None, minutes=43200)
    return UsageInfo(five_hour=None, seven_day=None, provider="codex", windows=[window])


def codex_used(limits: EngineLimits) -> list[float]:
    return [window.utilization for window in limits.windows]


class Rig:
    def __init__(self, db: Database, clock: FakeClock, tmp_path: Path) -> None:
        self.db = db
        self.clock = clock
        self.factory = FakeProbeFactory()
        self.store = UsageStore(db, clock)
        self.bus = EventBus(db, clock)
        self.visibility = ClientVisibility(clock)
        self.setting = Setting()
        self.codex = FakeCodex()
        self.refresher = UsageRefresher(
            store=self.store,
            bus=self.bus,
            clock=clock,
            probe=UsageProbe(self.factory, tmp_path),
            visibility=self.visibility,
            interval=self.setting,
            codex=self.codex,
            tick=timedelta(milliseconds=10),
        )

    async def usage_events(self, kind: str = types.USAGE_UPDATED) -> int:
        rows = await self.db.fetch_all("SELECT id FROM events WHERE type = ?", (kind,))
        return len(rows)


@pytest.fixture
def h(db: Database, clock: FakeClock, tmp_path: Path) -> Rig:
    return Rig(db, clock, tmp_path)


async def test_nothing_is_probed_while_no_client_is_visible(h: Rig) -> None:
    h.factory.replies.append(answer())

    await h.refresher.tick()

    assert h.factory.prompts == 0


async def test_a_visible_client_gets_fresh_limits(h: Rig) -> None:
    h.factory.replies.append(answer(0.42, 0.12))
    h.visibility.report("mac", visible=True)

    await h.refresher.tick()

    limits = await h.store.limits()
    assert limits.five_hour is not None
    assert (limits.five_hour.utilization, limits.five_hour.updated_at) == (0.42, h.clock.now())
    assert await h.usage_events() == 1
    month = await h.store.period("month", h.clock.now().date())
    assert (month.sessions, month.tokens.total) == (0, 0)
    assert month.probes.model_dump() == {"count": 1, "tokens": 452}


async def test_probes_repeat_every_interval_while_visible(h: Rig) -> None:
    h.factory.replies.extend([answer(0.1), answer(0.2)])
    h.visibility.report("mac", visible=True)
    await h.refresher.tick()

    h.clock.advance(INTERVAL - timedelta(seconds=1))
    h.visibility.report("mac", visible=True)
    await h.refresher.tick()
    assert h.factory.prompts == 1

    h.clock.advance(timedelta(seconds=1))
    await h.refresher.tick()
    assert h.factory.prompts == 2


async def test_limits_a_session_reported_within_the_interval_skip_the_probe(h: Rig) -> None:
    h.factory.replies.append(answer())
    h.visibility.report("phone", visible=True)
    await h.store.update_limits(
        UsageInfo(five_hour=UsageWindow(utilization=0.5, resets_at=None), seven_day=None)
    )

    h.clock.advance(INTERVAL - timedelta(seconds=1))
    h.visibility.report("phone", visible=True)
    await h.refresher.tick()
    assert h.factory.prompts == 0

    h.clock.advance(timedelta(seconds=1))
    await h.refresher.tick()
    assert h.factory.prompts == 1


async def test_no_probes_when_the_refresh_is_off(h: Rig) -> None:
    h.factory.replies.append(answer())
    h.visibility.report("mac", visible=True)
    h.setting.interval = None

    await h.refresher.tick()

    assert h.factory.prompts == 0


async def test_visibility_expires_without_a_heartbeat(h: Rig) -> None:
    h.factory.replies.extend([answer(), answer()])
    h.visibility.report("mac", visible=True)
    await h.refresher.tick()

    h.clock.advance(VISIBILITY_TTL)
    await h.refresher.tick()

    assert h.factory.prompts == 1


async def test_a_failed_probe_waits_for_the_next_interval(
    h: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    h.factory.replies.extend([RuntimeError("Invalid API key sk-ant-secret"), answer()])
    h.visibility.report("mac", visible=True)

    with caplog.at_level(logging.WARNING):
        await h.refresher.tick()
        await h.refresher.tick()

    assert h.factory.prompts == 1
    assert await h.usage_events() == 0
    assert "usage probe failed" in caplog.text
    assert "sk-ant" not in caplog.text
    h.clock.advance(INTERVAL)
    h.visibility.report("mac", visible=True)
    await h.refresher.tick()
    assert await h.usage_events() == 1


async def test_a_probe_without_windows_records_its_tokens_only(
    h: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    h.factory.replies.append([result()])
    h.visibility.report("mac", visible=True)

    with caplog.at_level(logging.WARNING):
        await h.refresher.tick()

    assert (await h.store.limits()).five_hour is None
    assert await h.usage_events() == 0
    assert "reported no usage windows" in caplog.text
    month = await h.store.period("month", h.clock.now().date())
    assert month.probes.count == 1


async def test_the_idle_probe_client_closes_after_ten_minutes(h: Rig) -> None:
    h.factory.replies.append(answer())
    h.visibility.report("mac", visible=True)
    await h.refresher.tick()
    h.visibility.report("mac", visible=False)

    h.clock.advance(IDLE_CLOSE - timedelta(seconds=1))
    await h.refresher.tick()
    assert h.factory.clients[0].disconnects == 0

    h.clock.advance(timedelta(seconds=1))
    await h.refresher.tick()
    assert h.factory.clients[0].disconnects == 1


async def test_a_forced_refresh_probes_without_a_visible_client(h: Rig) -> None:
    h.factory.replies.append(answer(0.7))
    h.setting.interval = None

    limits = await h.refresher.refresh()

    assert limits.five_hour is not None
    assert limits.five_hour.utilization == 0.7
    assert await h.usage_events() == 1


async def test_forced_refreshes_are_spaced(h: Rig) -> None:
    h.factory.replies.extend([answer(), answer()])
    await h.refresher.refresh()

    h.clock.advance(FORCED_SPACING - timedelta(seconds=5))
    with pytest.raises(RefreshTooSoonError) as caught:
        await h.refresher.refresh()
    assert caught.value.retry_after == 5
    assert caught.value.payload()["retry_after"] == 5

    h.clock.advance(timedelta(seconds=5))
    await h.refresher.refresh()
    assert h.factory.prompts == 2


async def test_a_failed_forced_refresh_says_so(h: Rig) -> None:
    h.factory.replies.append([result()])

    with pytest.raises(ProbeFailedError):
        await h.refresher.refresh()


async def test_the_loop_probes_when_a_client_becomes_visible(h: Rig) -> None:
    h.factory.replies.append(answer())
    h.refresher = UsageRefresher(
        store=h.store,
        bus=h.bus,
        clock=h.clock,
        probe=UsageProbe(h.factory, Path()),
        visibility=h.visibility,
        interval=h.setting,
        codex=h.codex,
        # Long enough that only the wake-up can start the probe within the test.
        tick=timedelta(hours=1),
    )
    await h.refresher.start()
    try:
        await asyncio.sleep(0)
        h.visibility.report("mac", visible=True)
        h.refresher.wake()
        for _ in range(100):
            if h.factory.prompts:
                break
            await asyncio.sleep(0.01)
    finally:
        await h.refresher.stop()

    assert h.factory.prompts == 1
    assert h.factory.clients[0].disconnects == 1


async def test_the_loop_survives_a_failing_tick(h: Rig, caplog: pytest.LogCaptureFixture) -> None:
    calls = 0

    async def failing() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError("database is locked")

    h.refresher.tick = failing  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        await h.refresher.start()
        for _ in range(100):
            if calls >= 2:
                break
            await asyncio.sleep(0.01)
        await h.refresher.stop()

    assert calls >= 2
    assert "usage refresh failed" in caplog.text


async def test_stopping_a_refresher_that_never_started(h: Rig) -> None:
    await h.refresher.stop()


def test_visibility_is_per_client(clock: FakeClock) -> None:
    visibility = ClientVisibility(clock)

    assert visibility.report("mac", visible=True) is True
    assert visibility.report("phone", visible=True) is False
    assert visibility.report("mac", visible=False) is False
    assert visibility.any_visible()
    visibility.report("phone", visible=False)
    assert not visibility.any_visible()
    assert visibility.report("phone", visible=False) is False


async def test_codex_windows_are_read_on_the_same_cadence_without_a_probe(h: Rig) -> None:
    h.factory.replies.extend([answer(), answer()])
    h.codex.replies.extend([codex_info(0.3), codex_info(0.4)])
    h.visibility.report("mac", visible=True)
    await h.refresher.tick()

    assert codex_used(await h.store.engine_limits("codex")) == [0.3]
    claude = await h.store.limits()
    assert claude.five_hour is not None
    assert claude.five_hour.utilization == 0.42
    assert await h.usage_events(types.USAGE_PROVIDER_UPDATED) == 1
    assert await h.usage_events() == 1
    # Claude's probe tokens only: reading Codex's windows runs no model.
    month = await h.store.period("month", h.clock.now().date())
    assert month.probes.count == 1

    h.clock.advance(INTERVAL - timedelta(seconds=1))
    h.visibility.report("mac", visible=True)
    await h.refresher.tick()
    assert h.codex.calls == 1
    h.clock.advance(timedelta(seconds=1))
    await h.refresher.tick()
    assert h.codex.calls == 2
    assert h.factory.prompts == 2


async def test_codex_windows_from_a_turn_put_off_the_next_read(h: Rig) -> None:
    h.factory.replies.append(answer())
    h.visibility.report("mac", visible=True)
    await h.store.update_limits(codex_info())

    await h.refresher.tick()

    assert (h.factory.prompts, h.codex.calls) == (1, 0)


async def test_codex_without_windows_publishes_nothing(h: Rig) -> None:
    h.visibility.report("mac", visible=True)
    h.factory.replies.append(answer())

    await h.refresher.tick()

    assert h.codex.calls == 1
    assert await h.usage_events(types.USAGE_PROVIDER_UPDATED) == 0
    assert (await h.store.engine_limits("codex")).windows == []


async def test_a_forced_codex_refresh_is_spaced_apart_from_claudes(h: Rig) -> None:
    h.factory.replies.append(answer())
    h.codex.replies.extend([codex_info(0.5), codex_info(0.6)])
    await h.refresher.refresh()

    limits = await h.refresher.refresh_engine("codex")

    assert codex_used(limits) == [0.5]
    h.clock.advance(FORCED_SPACING - timedelta(seconds=2))
    with pytest.raises(RefreshTooSoonError) as caught:
        await h.refresher.refresh_engine("codex")
    assert caught.value.retry_after == 2
    h.clock.advance(timedelta(seconds=2))
    assert codex_used(await h.refresher.refresh_engine("codex")) == [0.6]


async def test_a_failed_codex_refresh_names_codex(h: Rig) -> None:
    with pytest.raises(ProbeFailedError, match=r"^Codex did not report"):
        await h.refresher.refresh_engine("codex")
