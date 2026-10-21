"""B98: usage windows per account. Earlier windows are the first accounts', reads and
reports without an account mean the active one, and a window past its reset counts as
reset until a newer report comes.
"""

import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from nestd.providers.base import EngineWindow, UsageInfo, UsageWindow
from nestd.storage.db import Database
from nestd.storage.migrations import PACKAGED
from nestd.usage.store import UsageStore
from tests.fakes import FakeClock

SOON = datetime(2026, 1, 1, 15, tzinfo=UTC)
CLAUDE = UsageInfo(
    five_hour=UsageWindow(utilization=0.64, resets_at=SOON),
    seven_day=UsageWindow(utilization=0.2, resets_at=None),
)
CODEX = UsageInfo(
    five_hour=None,
    seven_day=None,
    provider="codex",
    windows=[
        EngineWindow(utilization=0.5, resets_at=None, minutes=10080),
        EngineWindow(utilization=0.3, resets_at=SOON, minutes=300),
    ],
)


async def test_earlier_windows_become_the_first_accounts(tmp_path: Path) -> None:
    before = tmp_path / "before"
    before.mkdir()
    for entry in PACKAGED.iterdir():
        if entry.name.endswith(".sql") and entry.name < "0038":
            (before / entry.name).write_text(entry.read_text(encoding="utf-8"), encoding="utf-8")
    path = tmp_path / "nest.db"
    old = await Database.open(path, before)
    await old.execute(
        "INSERT INTO usage_limits (provider, name, utilization, resets_at, updated_at, minutes)"
        " VALUES ('claude', 'five_hour', 0.4, NULL, '2026-01-01T12:00:00+00:00', NULL),"
        " ('codex', '300m', 0.1, NULL, '2026-01-01T12:00:00+00:00', 300)"
    )
    await old.close()
    shutil.rmtree(before)

    db = await Database.open(path)
    try:
        rows = await db.fetch_all("SELECT account_id, name FROM usage_limits ORDER BY name")
        accounts = await db.fetch_all(
            "SELECT id, provider, name, profile, position FROM engine_accounts ORDER BY id"
        )
        active = await db.fetch_all("SELECT * FROM active_accounts ORDER BY provider")
    finally:
        await db.close()

    assert [tuple(row) for row in rows] == [("codex-main", "300m"), ("claude-main", "five_hour")]
    assert [tuple(row) for row in accounts] == [
        ("claude-main", "claude", None, None, 0),
        ("codex-main", "codex", None, None, 0),
    ]
    assert [tuple(row) for row in active] == [("claude", "claude-main"), ("codex", "codex-main")]


async def test_each_account_keeps_its_own_windows_and_none_means_the_active_one(
    db: Database, clock: FakeClock
) -> None:
    active = {"claude": "claude-main", "codex": "codex-main"}
    usage = UsageStore(db, clock, active=active.__getitem__)
    await usage.update_limits(CLAUDE)
    await usage.update_limits(CLAUDE.model_copy(update={"five_hour": None}), "0123456789ab")
    await usage.update_limits(CODEX, "abcdefabcdef")
    active["claude"] = "0123456789ab"

    work, first = await usage.limits(), await usage.limits("claude-main")

    assert work.five_hour is None
    assert work.seven_day is not None
    assert first.five_hour is not None
    assert first.five_hour.utilization == 0.64
    assert (await usage.engine_limits("codex")).windows == []
    assert len((await usage.engine_limits("codex", "abcdefabcdef")).windows) == 2
    assert await usage.limits_updated_at("codex") is None
    assert await usage.limits_updated_at("codex", "abcdefabcdef") == clock.now()


async def test_an_accounts_windows_are_labelled_shortest_first_and_reset_once_past(
    db: Database, clock: FakeClock
) -> None:
    usage = UsageStore(db, clock)
    await usage.update_limits(CLAUDE)
    await usage.update_limits(CODEX, "abcdefabcdef")
    reported = clock.now()

    clock.current = SOON + timedelta(seconds=1)
    claude = await usage.windows("claude-main")
    codex = await usage.windows("abcdefabcdef")

    assert [w.model_dump() for w in claude] == [
        {
            "label": "5 hour",
            "minutes": 300,
            "utilization": 0.0,
            "resets_at": None,
            "updated_at": reported,
            "reset": True,
        },
        {
            "label": "Weekly",
            "minutes": 10080,
            "utilization": 0.2,
            "resets_at": None,
            "updated_at": reported,
            "reset": False,
        },
    ]
    assert [(w.label, w.reset) for w in codex] == [("5 hour", True), ("Weekly", False)]
    assert await usage.windows("nobody") == []


async def test_a_window_before_its_reset_is_as_reported(db: Database, clock: FakeClock) -> None:
    usage = UsageStore(db, clock)
    await usage.update_limits(CLAUDE)

    five_hour = (await usage.windows("claude-main"))[0]

    assert (five_hour.utilization, five_hour.resets_at, five_hour.reset) == (0.64, SOON, False)


async def test_a_window_of_unknown_length_comes_last(db: Database, clock: FakeClock) -> None:
    usage = UsageStore(db, clock)
    unsized = EngineWindow(utilization=0.9, resets_at=None, minutes=None)
    await usage.update_limits(CODEX.model_copy(update={"windows": [unsized, *CODEX.windows]}))

    assert [w.label for w in await usage.windows("codex-main")] == ["5 hour", "Weekly", "Usage"]


async def test_listeners_hear_which_accounts_windows_changed_and_forget_drops_them(
    db: Database, clock: FakeClock
) -> None:
    usage = UsageStore(db, clock)
    heard: list[str] = []

    async def listener(account_id: str) -> None:
        heard.append(account_id)

    usage.listen(listener)
    await usage.update_limits(CLAUDE)
    await usage.update_limits(CODEX, "abcdefabcdef")
    await usage.forget("abcdefabcdef")

    assert heard == ["claude-main", "abcdefabcdef"]
    assert await usage.windows("abcdefabcdef") == []
    assert len(await usage.windows("claude-main")) == 2
