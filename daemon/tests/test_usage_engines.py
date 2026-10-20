"""B91: usage per engine. Claude and Codex chats count together in the calendar with each
engine's part, each engine keeps its own windows, and Claude's payloads stay as before.
"""

import json
import shutil
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import EngineWindow, TokenUsage, UsageInfo, UsageWindow
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from nestd.storage.migrations import PACKAGED
from nestd.usage.publish import publish_usage
from nestd.usage.store import UsageStore
from tests.api_client import Api, running_api
from tests.codex_support import RATE_LIMITS, SIGNED_OUT, item, note, turn_completed
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach
from tests.test_session_store import new_session

CODEX = UsageInfo(
    five_hour=None,
    seven_day=None,
    provider="codex",
    windows=[
        EngineWindow(utilization=0.3, resets_at=datetime(2026, 1, 1, 16, tzinfo=UTC), minutes=43200)
    ],
)
CLAUDE = UsageInfo(five_hour=None, seven_day=UsageWindow(utilization=0.8, resets_at=None))


async def test_earlier_turns_and_windows_become_claudes(tmp_path: Path) -> None:
    before = tmp_path / "before"
    before.mkdir()
    for entry in PACKAGED.iterdir():
        if entry.name.endswith(".sql") and entry.name < "0034":
            (before / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "nest.db"
    old = await Database.open(path, before)
    await old.execute(
        "INSERT INTO turn_usage (session_id, repo, ts, input_tokens, output_tokens,"
        " cache_creation_input_tokens, cache_read_input_tokens)"
        " VALUES ('s1', 'repo', '2026-01-01T12:00:00+00:00', 1, 2, 3, 4)"
    )
    await old.execute(
        "INSERT INTO usage_limits (name, utilization, resets_at, updated_at)"
        " VALUES ('five_hour', 0.4, NULL, '2026-01-01T12:00:00+00:00')"
    )
    await old.close()
    shutil.rmtree(before)

    db = await Database.open(path)
    try:
        rows = await db.fetch_all("SELECT provider FROM turn_usage")
        usage = UsageStore(db, FakeClock())
        limits = await usage.limits()
        codex = await usage.engine_limits("codex")
        day = await usage.period("day", date(2026, 1, 1))
    finally:
        await db.close()

    assert [row["provider"] for row in rows] == ["claude"]
    assert limits.five_hour is not None
    assert limits.five_hour.utilization == 0.4
    assert codex.windows == []
    assert [e.model_dump() for e in day.engines] == [
        {"provider": "claude", "tokens": 10, "sessions": 1}
    ]


async def test_codex_windows_named_by_place_before_go_and_claudes_stay(tmp_path: Path) -> None:
    before = tmp_path / "before"
    before.mkdir()
    for entry in PACKAGED.iterdir():
        if entry.name.endswith(".sql") and entry.name < "0036":
            (before / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "nest.db"
    old = await Database.open(path, before)
    for provider in ("claude", "codex"):
        await old.execute(
            "INSERT INTO usage_limits (provider, name, utilization, resets_at, updated_at)"
            " VALUES (?, 'five_hour', 0.4, NULL, '2026-01-01T12:00:00+00:00')",
            (provider,),
        )
    await old.close()
    shutil.rmtree(before)

    db = await Database.open(path)
    try:
        usage = UsageStore(db, FakeClock())
        claude, codex = await usage.limits(), await usage.engine_limits("codex")
    finally:
        await db.close()

    assert claude.five_hour is not None
    assert codex.windows == []


async def test_a_period_counts_every_engine_and_splits_them(db: Database, clock: FakeClock) -> None:
    sessions = SessionStore(db, clock)
    usage = UsageStore(db, clock, UTC)
    claude = await sessions.create(new_session(provider="claude"))
    codex = await sessions.create(new_session(provider="codex", repo="other"))
    pixie = await sessions.create(new_session(provider="claude", repo="pixie:a"))
    gone = await sessions.create(new_session(provider="codex"))
    quiet = await sessions.create(new_session(provider="zed"))
    await usage.record_turn(claude.id, TokenUsage(input_tokens=10))
    await usage.record_subagent(claude.id, "msg_1", TokenUsage(output_tokens=5))
    await usage.record_turn(pixie.id, TokenUsage(output_tokens=1))
    await usage.record_turn(codex.id, TokenUsage(input_tokens=20, cache_read_input_tokens=7))
    await usage.record_turn(gone.id, TokenUsage(input_tokens=3))
    await usage.record_turn(quiet.id, TokenUsage())
    await sessions.delete(gone.id)

    day = await usage.period("day", clock.now().date())

    assert day.tokens.total == 46
    assert sum(bar.tokens for bar in day.bars) == 46
    assert [e.model_dump() for e in day.engines] == [
        {"provider": "claude", "tokens": 16, "sessions": 2},
        {"provider": "codex", "tokens": 30, "sessions": 2},
    ]
    clock.advance(timedelta(days=2))
    assert (await usage.period("day", clock.now().date())).engines == []


async def test_each_engine_keeps_its_own_windows(db: Database, clock: FakeClock) -> None:
    usage = UsageStore(db, clock)
    await usage.update_limits(CLAUDE)
    clock.advance(timedelta(minutes=3))
    await usage.update_limits(CODEX)

    claude, codex = await usage.limits(), await usage.engine_limits("codex")

    assert claude.five_hour is None
    assert claude.seven_day is not None
    assert claude.seven_day.utilization == 0.8
    assert [(w.minutes, w.label, w.utilization) for w in codex.windows] == [(43200, "30 day", 0.3)]
    assert await usage.limits_updated_at() == clock.now() - timedelta(minutes=3)
    assert await usage.limits_updated_at("codex") == clock.now()


async def test_an_engines_report_replaces_all_its_windows(db: Database, clock: FakeClock) -> None:
    """Codex reports its windows whole, so one its plan no longer has goes away."""
    usage = UsageStore(db, clock)
    plus = CODEX.model_copy(
        update={
            "windows": [
                EngineWindow(utilization=0.1, resets_at=None, minutes=300),
                EngineWindow(utilization=0.2, resets_at=None, minutes=10080),
            ]
        }
    )
    await usage.update_limits(CLAUDE)
    await usage.update_limits(CODEX)
    clock.advance(timedelta(minutes=1))
    await usage.update_limits(plus)
    unsized = EngineWindow(utilization=0.5, resets_at=None, minutes=None)

    codex = await usage.engine_limits("codex")
    assert [(w.minutes, w.label, w.updated_at) for w in codex.windows] == [
        (300, "5 hour", clock.now()),
        (10080, "Weekly", clock.now()),
    ]
    await usage.update_limits(CODEX.model_copy(update={"windows": [unsized]}))
    assert [(w.minutes, w.label) for w in (await usage.engine_limits("codex")).windows] == [
        (None, "Usage")
    ]
    assert (await usage.limits()).seven_day is not None


async def test_claudes_event_is_unchanged_and_codexs_names_its_engine(
    db: Database, clock: FakeClock
) -> None:
    bus = EventBus(db, clock)

    await publish_usage(bus, CLAUDE)
    await publish_usage(bus, CODEX)

    rows = await db.fetch_all("SELECT type, payload FROM events ORDER BY id")
    assert [(row["type"], json.loads(row["payload"])) for row in rows] == [
        (
            types.USAGE_UPDATED,
            {"five_hour": None, "seven_day": {"utilization": 0.8, "resets_at": None}},
        ),
        (
            types.USAGE_PROVIDER_UPDATED,
            {
                "provider": "codex",
                "windows": [
                    {
                        "utilization": 0.3,
                        "resets_at": "2026-01-01T16:00:00Z",
                        "minutes": 43200,
                        "label": "30 day",
                    }
                ],
            },
        ),
    ]


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def test_codexs_windows_are_served_apart_from_claudes(api: Api, clock: FakeClock) -> None:
    refreshed = await api.http.post("/api/usage/refresh", params={"provider": "codex"})

    assert refreshed.status_code == 200
    assert refreshed.json() == {
        "windows": [
            {
                "utilization": 0.3,
                "resets_at": "2026-01-01T16:00:00Z",
                "updated_at": "2026-01-01T12:00:00Z",
                "minutes": 300,
                "label": "5 hour",
            },
            {
                "utilization": 0.815,
                "resets_at": None,
                "updated_at": "2026-01-01T12:00:00Z",
                "minutes": 10080,
                "label": "Weekly",
            },
        ]
    }
    codex = await api.http.get("/api/usage/limits", params={"provider": "codex"})
    assert codex.json() == refreshed.json()
    claude = await api.http.get("/api/usage/limits")
    assert claude.json() == {"five_hour": None, "seven_day": None}
    assert api.probes.prompts == 0
    assert len(api.codex.requests("turn/start")) == 0
    bogus = await api.http.get("/api/usage/limits", params={"provider": "gemini"})
    assert bogus.status_code == 422


async def test_a_signed_out_codex_refresh_answers_502(api: Api) -> None:
    api.codex.answers["account/read"] = SIGNED_OUT

    response = await api.http.post("/api/usage/refresh", params={"provider": "codex"})

    assert response.status_code == 502
    assert response.json()["detail"].startswith("Codex did not report")
    assert api.codex.requests("account/rateLimits/read") == []


async def test_a_codex_turn_counts_as_codex_and_its_limits_as_codexs(
    api: Api, clock: FakeClock
) -> None:
    api.codex.script(
        note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
        note(
            "thread/tokenUsage/updated",
            threadId="thread-1",
            turnId="turn-1",
            tokenUsage={
                "total": {"inputTokens": 100, "outputTokens": 20},
                "last": {"inputTokens": 100, "outputTokens": 20},
                "modelContextWindow": 200_000,
            },
        ),
        note("account/rateLimits/updated", rateLimits=RATE_LIMITS["rateLimits"]),
        item("completed", {"type": "agentMessage", "id": "a1", "text": "Done"}),
        turn_completed(),
    )

    session = await create(api, provider="codex", mode="in_place")
    await reach(api, str(session["id"]), "idle", results=1)

    params = {"unit": "day", "date": "2026-01-01"}
    day = (await api.http.get("/api/usage/period", params=params)).json()
    assert day["tokens"]["total"] == 120
    assert day["engines"] == [{"provider": "codex", "tokens": 120, "sessions": 1}]
    codex = (await api.http.get("/api/usage/limits", params={"provider": "codex"})).json()
    assert [w["utilization"] for w in codex["windows"]] == [0.3, 0.815]
    claude = (await api.http.get("/api/usage/limits")).json()
    assert claude == {"five_hour": None, "seven_day": None}
    kinds = {row["type"] for row in await api.ctx.db.fetch_all("SELECT type FROM events")}
    assert types.USAGE_PROVIDER_UPDATED in kinds
    assert types.USAGE_UPDATED not in kinds
