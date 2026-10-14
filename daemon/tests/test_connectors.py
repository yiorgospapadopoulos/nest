import json
from datetime import timedelta

import pytest

from nestd.connectors.naming import display_name, group_of, manage_hint
from nestd.connectors.registry import ConnectorRegistry
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import McpServer
from nestd.storage.db import Database
from tests.fakes import FakeClock


@pytest.mark.parametrize(
    ("name", "display", "group", "hint"),
    [
        ("claude.ai Gmail", "Gmail", "claude.ai", "claude.ai"),
        ("claude.ai Google Drive", "Google Drive", "claude.ai", "claude.ai"),
        ("plugin:engineering:github", "github", "plugin", "claude_code"),
        ("plugin:serena:serena", "serena", "plugin", "claude_code"),
        ("plugin:odd", "odd", "plugin", "claude_code"),
        ("context7", "context7", "local", "claude_code"),
        ("claude.ai", "claude.ai", "local", "claude_code"),
    ],
)
def test_naming(name: str, display: str, group: str, hint: str) -> None:
    assert display_name(name) == display
    assert group_of(name) == group
    assert manage_hint(group_of(name)) == hint


@pytest.fixture
def bus(db: Database, clock: FakeClock) -> EventBus:
    return EventBus(db, clock)


async def test_reports_keep_the_latest_status_and_announce_changes(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    registry = ConnectorRegistry(db, clock, bus)
    first_seen = clock.now()

    await registry.report(
        "s1",
        [
            McpServer("plugin:engineering:github", "needs-auth"),
            McpServer("claude.ai Gmail", "pending"),
            McpServer("local-db", "failed"),
        ],
    )
    clock.advance(timedelta(minutes=1))
    await registry.report("s2", [McpServer("claude.ai Gmail", "connected")])
    clock.advance(timedelta(minutes=1))
    await registry.report("s3", [McpServer("claude.ai Gmail", "connected")])
    connectors = await registry.list_connectors()

    assert [(c.name, c.display_name, c.group, c.status, c.manage_hint) for c in connectors] == [
        ("claude.ai Gmail", "Gmail", "claude.ai", "connected", "claude.ai"),
        ("plugin:engineering:github", "github", "plugin", "needs-auth", "claude_code"),
        ("local-db", "local-db", "local", "failed", "claude_code"),
    ]
    assert (connectors[0].source, connectors[0].last_seen_at) == ("s3", clock.now())
    assert (connectors[1].source, connectors[1].last_seen_at) == ("s1", first_seen)
    published = await db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.CONNECTORS_UPDATED,)
    )
    # The third report changed nothing.
    assert len(published) == 2
    assert published[-1]["session_id"] is None
    latest = json.loads(published[-1]["payload"])["connectors"]
    assert [(c["name"], c["status"], c["source"]) for c in latest] == [
        ("claude.ai Gmail", "connected", "s2"),
        ("plugin:engineering:github", "needs-auth", "s1"),
        ("local-db", "failed", "s1"),
    ]


async def test_an_empty_report_changes_nothing(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    registry = ConnectorRegistry(db, clock, bus)

    await registry.report("s1", [])

    assert await registry.list_connectors() == []
    assert await db.fetch_all("SELECT * FROM events") == []


async def test_pending_never_replaces_a_known_status(
    db: Database, clock: FakeClock, bus: EventBus
) -> None:
    registry = ConnectorRegistry(db, clock, bus)
    await registry.report("s1", [McpServer("claude.ai Gmail", "pending")])
    await registry.report(
        "s1", [McpServer("claude.ai Gmail", "connected"), McpServer("db", "failed", "ENOENT")]
    )
    clock.advance(timedelta(minutes=1))

    # A new run's init reports everything as pending while it connects.
    await registry.report(
        "s2", [McpServer("claude.ai Gmail", "pending"), McpServer("db", "pending")]
    )
    connectors = {c.name: c for c in await registry.list_connectors()}

    assert (connectors["claude.ai Gmail"].status, connectors["claude.ai Gmail"].error) == (
        "connected",
        None,
    )
    assert (connectors["db"].status, connectors["db"].error) == ("failed", "ENOENT")
    assert (connectors["db"].source, connectors["db"].last_seen_at) == ("s2", clock.now())
    published = await db.fetch_all(
        "SELECT id FROM events WHERE type = ?", (types.CONNECTORS_UPDATED,)
    )
    assert len(published) == 2


async def test_a_changed_error_is_announced(db: Database, clock: FakeClock, bus: EventBus) -> None:
    registry = ConnectorRegistry(db, clock, bus)
    await registry.report("s1", [McpServer("db", "failed", "ENOENT")])

    await registry.report("s1", [McpServer("db", "failed", "timeout")])

    (connector,) = await registry.list_connectors()
    assert connector.error == "timeout"
    published = await db.fetch_all(
        "SELECT id FROM events WHERE type = ?", (types.CONNECTORS_UPDATED,)
    )
    assert len(published) == 2
