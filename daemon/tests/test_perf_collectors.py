"""B115: the collectors that count from Nest's own records, and the context breakdown."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from nestd.events import types
from nestd.events.bus import EventBus
from nestd.perf.collectors.activity import Activity
from nestd.perf.collectors.common import first_event_since
from nestd.perf.collectors.context import breakdown
from nestd.perf.collectors.engines import Engines, Target
from nestd.perf.collectors.turns import TurnSpeed
from nestd.perf.models import Collected, Measured
from nestd.providers.base import RunAccount, TokenUsage
from nestd.storage.db import Database
from tests.fake_provider import FakeProvider, reply
from tests.fakes import FakeClock

NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


async def add_session(db: Database, session_id: str, provider: str = "claude") -> None:
    await db.execute(
        "INSERT INTO sessions (id, repo, title, prompt, mode, state, permission_mode, provider,"
        " created_at, updated_at)"
        " VALUES (?, 'nest', 't', 'p', 'in_place', 'idle', 'default', ?, 'x', 'x')",
        (session_id, provider),
    )


async def add_usage(
    db: Database,
    at: datetime,
    session_id: str = "s1",
    provider: str = "claude",
    subagent: bool = False,
    tokens: tuple[int, int, int, int] = (10, 20, 30, 40),
) -> None:
    await db.execute(
        "INSERT INTO turn_usage (session_id, repo, ts, input_tokens, output_tokens,"
        " cache_creation_input_tokens, cache_read_input_tokens, subagent, provider)"
        " VALUES (?, 'nest', ?, ?, ?, ?, ?, ?, ?)",
        (session_id, at.isoformat(), *tokens, int(subagent), provider),
    )


def values(collected: Collected) -> dict[str, float | None]:
    return {m.id: m.value for m in collected.metrics}


def metric(collected: Collected, metric_id: str) -> Measured:
    return next(m for m in collected.metrics if m.id == metric_id)


async def test_activity_counts_turns_chats_and_tokens_per_day(
    db: Database, clock: FakeClock
) -> None:
    clock.current = NOW
    for days_ago, session_id in ((0, "a"), (0, "a"), (0, "b"), (3, "a"), (30, "c"), (95, "old")):
        await add_usage(db, NOW - timedelta(days=days_ago), session_id)
    # A subagent reply adds tokens but is not a turn.
    await add_usage(db, NOW, "a", subagent=True, tokens=(0, 100, 0, 0))

    collected = await Activity(db, clock, UTC)()

    found = values(collected)
    assert found["turns_14"] == 4 / 14
    assert found["turns_90"] == 5 / 90
    # Chats a day: distinct chats with a turn, each day.
    assert found["chats_14"] == (2 + 1) / 14
    assert found["tokens_14"] == (4 * 100 + 100) / 14
    assert collected.series is not None
    points = collected.series.points
    assert len(points) == 14
    assert (points[-1].day, points[-1].value) == (date(2026, 11, 2), 3)
    assert points[-4].value == 1
    assert all(m.better == "none" for m in collected.metrics)


async def test_turn_speed_reads_first_reply_and_length_from_the_events(
    db: Database, clock: FakeClock
) -> None:
    clock.current = NOW - timedelta(days=10)
    bus = EventBus(db, clock)
    await add_session(db, "c1")
    await add_session(db, "x1", "codex")

    async def turn(session_id: str, reply_after: float | None, length_ms: int) -> None:
        await bus.publish(types.SESSION_STATE, {"state": "running", "turn_start": True}, session_id)
        if reply_after is not None:
            clock.advance(timedelta(seconds=reply_after))
            await bus.publish(types.SESSION_MESSAGE, {"blocks": []}, session_id)
            clock.advance(timedelta(seconds=0.5))
            await bus.publish(types.SESSION_MESSAGE, {"blocks": []}, session_id)
        await bus.publish(
            types.SESSION_STATE, {"state": "idle", "duration_ms": length_ms}, session_id
        )
        clock.advance(timedelta(minutes=1))

    # Older than the week: left out.
    await turn("c1", 50, 90_000)
    clock.current = NOW - timedelta(days=1)
    await turn("c1", 1, 4_000)
    await turn("c1", 3, 10_000)
    await turn("x1", 2, 6_000)
    # A turn that failed before any reply still counts for its length.
    await turn("x1", None, 500)
    await add_usage(db, NOW, "c1", tokens=(10, 5, 10, 80))
    await add_usage(db, NOW, "x1", "codex", tokens=(50, 5, 0, 50))
    clock.current = NOW

    collected = await TurnSpeed(db, clock)()

    found = values(collected)
    assert found["first_reply"] == 2000
    assert found["typical"] == 5000
    assert found["slowest"] == 10_000
    # Cache read over all input: (80 + 50) / (100 + 100).
    assert found["cache_rate"] == 65
    assert found["first_reply_claude"] == 2000
    assert found["typical_codex"] == 3250
    assert found["cache_rate_codex"] == 50
    assert metric(collected, "typical").sub == "4 turns"


async def test_a_turn_that_waits_on_you_still_counts(db: Database, clock: FakeClock) -> None:
    """Regression: a state change inside a turn (waiting for an approval, then running
    again) dropped the turn, so the slow turns that waited on you were never counted."""
    clock.current = NOW - timedelta(hours=1)
    bus = EventBus(db, clock)
    await add_session(db, "c1")
    await bus.publish(types.SESSION_STATE, {"state": "running", "turn_start": True}, "c1")
    clock.advance(timedelta(seconds=2))
    await bus.publish(types.SESSION_MESSAGE, {"blocks": []}, "c1")
    await bus.publish(types.SESSION_STATE, {"state": "waiting"}, "c1")
    await bus.publish(types.SESSION_STATE, {"state": "running"}, "c1")
    await bus.publish(types.SESSION_STATE, {"state": "idle", "duration_ms": 90_000}, "c1")
    clock.current = NOW

    found = values(await TurnSpeed(db, clock)())

    assert found["typical"] == 90_000
    assert found["first_reply"] == 2000


async def test_the_first_event_of_a_window_is_found_across_gaps(
    db: Database, clock: FakeClock
) -> None:
    bus = EventBus(db, clock)
    clock.current = NOW - timedelta(days=40)
    for _ in range(20):
        await bus.publish(types.NOTIFY, {})
        clock.advance(timedelta(days=1))
    await db.execute("DELETE FROM events WHERE id IN (8, 9, 10)")

    first = await first_event_since(db, NOW - timedelta(days=30))

    rows = await db.fetch_all("SELECT ts FROM events WHERE id >= ?", (first,))
    earlier = await db.fetch_all("SELECT ts FROM events WHERE id < ?", (first,))
    cutoff = NOW - timedelta(days=30)
    assert len(rows) == 10
    assert all(datetime.fromisoformat(r["ts"]) >= cutoff for r in rows)
    assert all(datetime.fromisoformat(r["ts"]) < cutoff for r in earlier)
    assert await first_event_since(db, NOW) > max(
        int(r["id"]) for r in await db.fetch_all("SELECT id FROM events")
    )


def test_the_context_breakdown_from_claude_codes_report() -> None:
    """The shape Claude Code 2.x reported in a live check (B115), cut down."""
    raw: dict[str, object] = {
        "categories": [
            {"name": "System prompt", "tokens": 6872, "kind": "used"},
            {"name": "System tools", "tokens": 10572, "kind": "used"},
            {"name": "MCP server instructions", "tokens": 3442, "kind": "used"},
            {"name": "MCP tools (deferred)", "tokens": 195325, "isDeferred": True},
            {"name": "System tools (deferred)", "tokens": 18366, "isDeferred": True},
            {"name": "Memory files", "tokens": 775, "kind": "used"},
            {"name": "Skills", "tokens": 2160, "kind": "used"},
            {"name": "Messages", "tokens": 1695, "kind": "used"},
            {"name": "Free space", "tokens": 174484, "kind": "free"},
        ],
        "totalTokens": 25516,
        "maxTokens": 200000,
        "percentage": 13,
        "model": "claude-haiku-4-5-20251001",
        "mcpTools": [
            {
                "name": "mcp__a__x",
                "serverName": "claude_ai_Gmail",
                "tokens": 400,
                "isLoaded": False,
            },
            {"name": "mcp__b__y", "serverName": "plugin_serena", "tokens": 90, "isLoaded": False},
        ],
        "skills": {"totalSkills": 95, "includedSkills": 95, "tokens": 2160},
    }

    collected = breakdown(raw, nest_prompt=300, nest_tools=900, claude_md=(3100, None))

    found = values(collected)
    # A new chat has no messages yet: the measuring turn's own are left out.
    assert found["total"] == 25516 - 1695
    assert found["share"] == (25516 - 1695) / 200000 * 100
    assert found["system_prompt"] == 6872 - 300
    assert found["tools"] == 10572
    # Tool search deferred Nest's tools with the rest: none of them counts as loaded.
    assert found["mcp_tools"] == 3442
    assert (found["memory"], found["skills"]) == (775, 2160)
    assert (found["nest_prompt"], found["nest_tools"]) == (300, 0)
    assert metric(collected, "nest_tools").sub == "deferred by tool search"
    # Regression: the parts add up to the total (deferred Nest tools were counted in both).
    parts = metric(collected, "total").parts or []
    assert sum(p.value for p in parts) == found["total"]
    assert found["without_tool_search"] == 25516 - 1695 + 195325 + 18366
    assert metric(collected, "total").sub == "of 200k"
    assert collected.facts == {
        "mcp_servers": ["claude_ai_Gmail", "plugin_serena"],
        "skills": 95,
        "user_claude_md": 3100,
        "general_claude_md": None,
        "model": "claude-haiku-4-5-20251001",
    }


async def test_engines_run_the_tiny_task_on_each_engine_without_a_chat(
    tmp_path: Path, db: Database
) -> None:
    provider = FakeProvider()
    provider.script(reply("ok", tokens=TokenUsage(input_tokens=400, output_tokens=5)))

    async def model() -> str | None:
        return "haiku"

    async def account() -> RunAccount | None:
        return None

    async def targets() -> list[Target]:
        return [Target(provider, model, account)]

    collected = await Engines(targets, tmp_path / "perf")()

    found = values(collected)
    assert found["fake_tokens"] == 405
    assert found["fake_first"] is not None
    assert found["fake_total"] is not None
    assert metric(collected, "fake_first").sub == "haiku"
    run = provider.runs[0]
    assert (run.spec.model, run.spec.cwd, run.inputs[0].text) == (
        "haiku",
        tmp_path / "perf",
        "Reply with the word ok",
    )
    assert run.closed
    # Nor in the engine's own history (Claude Code transcripts, Codex threads).
    assert run.spec.keep_history is False
    row = await db.fetch_one("SELECT COUNT(*) AS n FROM sessions")
    assert row is not None
    assert row["n"] == 0
