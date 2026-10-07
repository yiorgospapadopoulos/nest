import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest

from harness.engine.fetch import FetchError, fetch_details, info_options
from harness.engine.models import FALLBACK_MODELS, ModelList
from harness.engine.service import EngineInfo, effort_problem
from harness.engine.store import EngineInfoStore
from harness.errors import InvalidInputError
from harness.providers.base import AccountInfo, EngineDetails, ModelOption
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_engine import LEVELS, FakeInfoFactory, server_info
from tests.fakes import START, FakeClock

OPUS = ModelOption(
    value="opus",
    display_name="Opus",
    description="opus model",
    effort_levels=LEVELS,
    supports_effort=True,
)
HAIKU = ModelOption(value="haiku", display_name="Haiku", description="haiku model")
ACCOUNT = AccountInfo(email="person@example.com", plan="Claude Max", organization="Acme")


class Harness:
    def __init__(self, db: Database, clock: FakeClock) -> None:
        self.db = db
        self.clock = clock
        self.factory = FakeInfoFactory(info=server_info("default", "opus", "haiku"))
        self.store = EngineInfoStore(db, clock)
        self.engine = self.build()

    def build(self, **timing: timedelta) -> EngineInfo:
        return EngineInfo(
            store=self.store,
            fetch=lambda: fetch_details(self.factory, timedelta(seconds=1)),
            clock=self.clock,
            **timing,
        )


@pytest.fixture
def h(db: Database, clock: FakeClock) -> Harness:
    return Harness(db, clock)


def test_the_fetch_loads_only_user_settings_without_tools_or_a_transcript(
    tmp_path: Path,
) -> None:
    options = info_options(tmp_path)

    assert options.cwd == tmp_path
    assert options.setting_sources == ["user"]
    assert options.tools == []
    assert options.strict_mcp_config is True
    assert options.extra_args == {"no-session-persistence": None}


async def test_a_fetch_reads_the_initialize_response_in_a_temporary_folder() -> None:
    factory = FakeInfoFactory(info=server_info("opus", "haiku"))

    details = await fetch_details(factory)

    (client,) = factory.clients
    assert details == EngineDetails(models=[OPUS, HAIKU], account=ACCOUNT)
    assert client.cwd_existed
    assert client.options.cwd is not None
    assert not await asyncio.to_thread(Path(client.options.cwd).exists)
    assert client.disconnects == 1


@pytest.mark.parametrize(
    ("factory", "reason"),
    [
        (FakeInfoFactory(connect_error=RuntimeError("secret output")), "RuntimeError"),
        (FakeInfoFactory(hang=True), "timed out"),
        (FakeInfoFactory(info=None), "Claude Code reported no models or account"),
        (FakeInfoFactory(info={"commands": []}), "Claude Code reported no models or account"),
    ],
)
async def test_a_failed_fetch_names_only_the_kind_of_error(
    factory: FakeInfoFactory, reason: str
) -> None:
    with pytest.raises(FetchError) as caught:
        await fetch_details(factory, timedelta(milliseconds=20))

    assert str(caught.value) == reason
    assert factory.clients[0].disconnects == 1


async def test_a_failing_disconnect_does_not_lose_the_details() -> None:
    factory = FakeInfoFactory(disconnect_error=RuntimeError("gone"))

    details = await fetch_details(factory)

    assert details.models is not None


async def test_before_any_report_the_fallback_list_and_an_empty_account_apply(
    h: Harness,
) -> None:
    assert await h.engine.models() == ModelList(models=list(FALLBACK_MODELS), updated_at=None)
    assert [m.value for m in FALLBACK_MODELS] == ["default", "opus", "sonnet", "haiku"]
    assert FALLBACK_MODELS[3].effort_levels == []
    assert await h.engine.account() == AccountInfo()
    assert await h.engine.find("opus") is None


async def test_a_refresh_stores_the_models_and_account(h: Harness) -> None:
    assert await h.engine.refresh()

    models = await h.engine.models()
    assert [m.value for m in models.models] == ["default", "opus", "haiku"]
    assert models.updated_at == START
    assert await h.engine.account() == ACCOUNT
    assert await h.engine.find("opus") == OPUS
    assert await h.engine.find(None) == models.models[0]
    assert await h.engine.find("claude-unknown") is None


async def test_the_cache_survives_a_restart(h: Harness) -> None:
    await h.engine.refresh()

    restarted = EngineInfo(store=EngineInfoStore(h.db, h.clock), fetch=_never_called, clock=h.clock)

    assert (await restarted.models()).updated_at == START
    assert await restarted.account() == ACCOUNT


async def test_a_failed_refresh_keeps_the_cache_and_logs_the_kind(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    await h.engine.refresh()
    h.factory.connect_error = RuntimeError("person@example.com said no")
    h.clock.advance(timedelta(hours=7))

    with caplog.at_level(logging.WARNING):
        assert not await h.engine.refresh()

    assert (await h.engine.models()).updated_at == START
    assert "RuntimeError" in caplog.text
    assert "person@example.com" not in caplog.text


async def test_a_report_with_only_an_account_keeps_the_models(h: Harness) -> None:
    await h.engine.refresh()
    h.clock.advance(timedelta(minutes=5))

    await h.engine.report(EngineDetails(account=AccountInfo(plan="Claude Pro")))

    assert (await h.engine.models()).updated_at == START
    assert await h.engine.account() == AccountInfo(plan="Claude Pro")


async def test_a_report_from_a_session_replaces_the_list(h: Harness) -> None:
    await h.engine.report(EngineDetails(models=[HAIKU]))

    assert await h.engine.models() == ModelList(models=[HAIKU], updated_at=START)
    assert await h.engine.account() == AccountInfo()


async def test_ticks_fetch_at_start_then_every_six_hours(h: Harness) -> None:
    await h.engine.tick()
    h.clock.advance(timedelta(hours=5, minutes=59))
    await h.engine.tick()
    h.clock.advance(timedelta(minutes=1))
    await h.engine.tick()

    assert len(h.factory.clients) == 2


async def test_a_session_report_postpones_the_next_fetch(h: Harness) -> None:
    await h.engine.tick()
    h.clock.advance(timedelta(hours=5))
    await h.engine.report(EngineDetails(models=[HAIKU]))
    h.clock.advance(timedelta(hours=2))
    await h.engine.tick()

    assert len(h.factory.clients) == 1


async def test_a_failed_fetch_is_retried_after_half_an_hour(h: Harness) -> None:
    h.factory.connect_error = RuntimeError("down")
    await h.engine.tick()
    h.clock.advance(timedelta(minutes=29))
    await h.engine.tick()
    h.factory.connect_error = None
    h.clock.advance(timedelta(minutes=1))
    await h.engine.tick()

    assert len(h.factory.clients) == 2
    assert (await h.engine.models()).updated_at is not None


async def test_the_loop_waits_briefly_then_fetches_and_stops_cleanly(h: Harness) -> None:
    engine = h.build(start_delay=timedelta(milliseconds=10), tick=timedelta(milliseconds=10))

    async def stored() -> bool:
        return (await engine.models()).updated_at == START

    await engine.start()
    await until(stored)
    await engine.stop()
    await engine.stop()

    assert len(h.factory.clients) == 1


async def test_stopping_during_the_start_delay_never_fetches(h: Harness) -> None:
    engine = h.build(start_delay=timedelta(hours=1))

    await engine.start()
    await asyncio.sleep(0.01)
    await engine.stop()

    assert h.factory.clients == []


async def test_the_loop_survives_a_failing_tick(
    h: Harness, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken() -> EngineDetails:
        raise RuntimeError("database is locked")

    engine = EngineInfo(
        store=h.store,
        fetch=broken,
        clock=h.clock,
        start_delay=timedelta(0),
        tick=timedelta(milliseconds=10),
        retry=timedelta(0),
    )

    with caplog.at_level(logging.WARNING):
        await engine.start()
        await until(lambda: "engine info check failed" in caplog.text)
        await engine.stop()


async def test_effort_is_checked_against_the_model_levels(h: Harness) -> None:
    await h.engine.refresh()

    await h.engine.require_effort("opus", "xhigh")
    await h.engine.require_effort("haiku", None)
    await h.engine.require_effort("claude-unknown", "max")
    with pytest.raises(InvalidInputError, match="Haiku does not take a thinking level"):
        await h.engine.require_effort("haiku", "low")


async def test_effort_is_not_checked_against_the_fallback_list(h: Harness) -> None:
    await h.engine.require_effort("haiku", "max")


def test_effort_problems_name_the_levels() -> None:
    limited = OPUS.model_copy(update={"effort_levels": ["low", "high"]})

    assert effort_problem(limited, "low") is None
    assert effort_problem(limited, None) is None
    assert effort_problem(limited, "max") == "Opus takes these thinking levels: low, high"
    assert effort_problem(HAIKU, "low") == "Haiku does not take a thinking level"


async def _never_called() -> EngineDetails:
    raise AssertionError
