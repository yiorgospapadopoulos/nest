import asyncio
import json
import logging
from datetime import timedelta
from pathlib import Path
from typing import TypedDict, Unpack

import pytest

from nestd.engine.fetch import FetchError, fetch_details, info_options
from nestd.engine.models import FALLBACK_MODELS, ModelList
from nestd.engine.service import EngineInfo, effort_problem
from nestd.engine.store import EngineInfoStore
from nestd.errors import InvalidInputError
from nestd.providers.base import AccountInfo, EngineDetails, ModelOption
from nestd.storage.db import Database
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


class Timing(TypedDict, total=False):
    start_delay: timedelta
    interval: timedelta
    retry: timedelta
    tick: timedelta


class Rig:
    def __init__(self, db: Database, clock: FakeClock) -> None:
        self.db = db
        self.clock = clock
        self.factory = FakeInfoFactory(info=server_info("default", "opus", "haiku"))
        self.store = EngineInfoStore(db, clock)
        self.engine = self.build()

    def build(self, **timing: Unpack[Timing]) -> EngineInfo:
        return EngineInfo(
            store=self.store,
            fetch=lambda: fetch_details(self.factory, timedelta(seconds=1)),
            clock=self.clock,
            account_file=None,
            settings_file=None,
            **timing,
        )


@pytest.fixture
def h(db: Database, clock: FakeClock) -> Rig:
    return Rig(db, clock)


def test_the_fetch_loads_only_user_settings_without_tools_hooks_or_a_transcript(
    tmp_path: Path,
) -> None:
    options = info_options(tmp_path)

    assert options.cwd == tmp_path
    assert options.setting_sources == ["user"]
    assert options.tools == []
    assert options.strict_mcp_config is True
    assert options.extra_args == {"no-session-persistence": None}
    # PL-16: no SessionStart or SessionEnd hook of the user's runs (and may call a model).
    assert options.settings is not None
    assert json.loads(options.settings) == {"disableAllHooks": True}


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
    h: Rig,
) -> None:
    assert await h.engine.models() == ModelList(
        models=list(FALLBACK_MODELS), updated_at=None, default_model="opus"
    )
    # No entry that defers to Claude Code: menus list only real models (B94).
    assert [m.value for m in FALLBACK_MODELS] == ["opus", "sonnet", "haiku"]
    assert FALLBACK_MODELS[2].effort_levels == []
    assert await h.engine.account() == AccountInfo()
    assert await h.engine.find("opus") is None
    # Nest names no default model before Claude Code reported its own.
    assert await h.engine.default_model() is None


async def test_a_refresh_stores_the_models_and_account(h: Rig) -> None:
    assert await h.engine.refresh()

    models = await h.engine.models()
    assert [m.value for m in models.models] == ["opus", "haiku"]
    assert models.default_model == "opus"
    assert models.updated_at == START
    assert await h.engine.account() == ACCOUNT
    assert await h.engine.find("opus") == OPUS
    # A chat from before B94 without a model still finds Claude Code's default entry.
    assert (await h.engine.find(None)).value == "default"  # type: ignore[union-attr]
    assert await h.engine.find("claude-unknown") is None
    assert await h.engine.default_model() == "opus"


async def test_a_report_with_an_account_says_claude_is_signed_in(h: Rig) -> None:
    seen: list[str] = []

    async def signed_in() -> None:
        seen.append("claude")

    engine = EngineInfo(store=h.store, fetch=_never_called, clock=h.clock, on_signed_in=signed_in)
    await engine.report(EngineDetails(models=[OPUS], account=None))
    await engine.report(EngineDetails(models=None, account=AccountInfo()))
    await engine.report(EngineDetails(models=None, account=ACCOUNT))

    assert seen == ["claude"]


async def test_the_cache_survives_a_restart(h: Rig) -> None:
    await h.engine.refresh()

    restarted = EngineInfo(store=EngineInfoStore(h.db, h.clock), fetch=_never_called, clock=h.clock)

    assert (await restarted.models()).updated_at == START
    assert await restarted.account() == ACCOUNT


async def test_a_failed_refresh_keeps_the_cache_and_logs_the_kind(
    h: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    await h.engine.refresh()
    h.factory.connect_error = RuntimeError("person@example.com said no")
    h.clock.advance(timedelta(hours=7))

    with caplog.at_level(logging.WARNING):
        assert not await h.engine.refresh()

    assert (await h.engine.models()).updated_at == START
    assert "RuntimeError" in caplog.text
    assert "person@example.com" not in caplog.text


def _profile(home: Path, name: str) -> Path:
    path = home / ".claude.json"
    path.write_text(json.dumps({"oauthAccount": {"displayName": name}}), encoding="utf-8")
    return path


async def test_without_an_engine_name_the_claude_code_profile_name_is_shown(
    h: Rig, tmp_path: Path
) -> None:
    path = _profile(tmp_path, "Giorgos")
    engine = EngineInfo(store=h.store, fetch=_never_called, clock=h.clock, account_file=path)

    assert await engine.account() == AccountInfo(display_name="Giorgos")
    await engine.report(EngineDetails(account=ACCOUNT))
    assert await engine.account() == ACCOUNT.model_copy(update={"display_name": "Giorgos"})

    # Read again on every request, so a rename shows at the next refresh.
    _profile(tmp_path, "Giorgos P.")
    assert (await engine.account()).display_name == "Giorgos P."
    path.unlink()
    assert (await engine.account()).display_name is None
    assert (await h.store.account()) == ACCOUNT


async def test_the_engines_own_display_name_wins(h: Rig, tmp_path: Path) -> None:
    path = _profile(tmp_path, "From the file")
    engine = EngineInfo(store=h.store, fetch=_never_called, clock=h.clock, account_file=path)

    await engine.report(EngineDetails(account=AccountInfo(display_name="From the engine")))

    assert (await engine.account()).display_name == "From the engine"


async def test_a_report_with_only_an_account_keeps_the_models(h: Rig) -> None:
    await h.engine.refresh()
    h.clock.advance(timedelta(minutes=5))

    await h.engine.report(EngineDetails(account=AccountInfo(plan="Claude Pro")))

    assert (await h.engine.models()).updated_at == START
    assert await h.engine.account() == AccountInfo(plan="Claude Pro")


async def test_a_report_from_a_session_replaces_the_list(h: Rig) -> None:
    await h.engine.report(EngineDetails(models=[HAIKU]))

    assert await h.engine.models() == ModelList(
        models=[HAIKU], updated_at=START, default_model="haiku"
    )
    assert await h.engine.account() == AccountInfo()


async def test_ticks_fetch_at_start_then_every_six_hours(h: Rig) -> None:
    await h.engine.tick()
    h.clock.advance(timedelta(hours=5, minutes=59))
    await h.engine.tick()
    h.clock.advance(timedelta(minutes=1))
    await h.engine.tick()

    assert len(h.factory.clients) == 2


async def test_a_session_report_postpones_the_next_fetch(h: Rig) -> None:
    await h.engine.tick()
    h.clock.advance(timedelta(hours=5))
    await h.engine.report(EngineDetails(models=[HAIKU]))
    h.clock.advance(timedelta(hours=2))
    await h.engine.tick()

    assert len(h.factory.clients) == 1


async def test_a_failed_fetch_is_retried_after_half_an_hour(h: Rig) -> None:
    h.factory.connect_error = RuntimeError("down")
    await h.engine.tick()
    h.clock.advance(timedelta(minutes=29))
    await h.engine.tick()
    h.factory.connect_error = None
    h.clock.advance(timedelta(minutes=1))
    await h.engine.tick()

    assert len(h.factory.clients) == 2
    assert (await h.engine.models()).updated_at is not None


async def test_the_loop_waits_briefly_then_fetches_and_stops_cleanly(h: Rig) -> None:
    engine = h.build(start_delay=timedelta(milliseconds=10), tick=timedelta(milliseconds=10))

    async def stored() -> bool:
        return (await engine.models()).updated_at == START

    await engine.start()
    await until(stored)
    await engine.stop()
    await engine.stop()

    assert len(h.factory.clients) == 1


async def test_stopping_during_the_start_delay_never_fetches(h: Rig) -> None:
    engine = h.build(start_delay=timedelta(hours=1))

    await engine.start()
    await asyncio.sleep(0.01)
    await engine.stop()

    assert h.factory.clients == []


async def test_the_loop_survives_a_failing_tick(h: Rig, caplog: pytest.LogCaptureFixture) -> None:
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


async def test_effort_is_checked_against_the_model_levels(h: Rig) -> None:
    await h.engine.refresh()

    await h.engine.require_effort("opus", "xhigh")
    await h.engine.require_effort("haiku", None)
    await h.engine.require_effort("claude-unknown", "max")
    with pytest.raises(InvalidInputError, match="Haiku does not take a thinking level"):
        await h.engine.require_effort("haiku", "low")


async def test_effort_is_not_checked_against_the_fallback_list(h: Rig) -> None:
    await h.engine.require_effort("haiku", "max")


def test_effort_problems_name_the_levels() -> None:
    limited = OPUS.model_copy(update={"effort_levels": ["low", "high"]})

    assert effort_problem(limited, "low") is None
    assert effort_problem(limited, None) is None
    assert effort_problem(limited, "max") == "Opus takes these thinking levels: low, high"
    assert effort_problem(HAIKU, "low") == "Haiku does not take a thinking level"


async def _never_called() -> EngineDetails:
    raise AssertionError
