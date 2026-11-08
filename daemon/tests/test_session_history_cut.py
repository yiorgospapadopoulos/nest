"""D174: on an engine that cannot cut its conversation, a rewound chat's next message gives
a new engine session the part of the chat that was kept.
"""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.events.models import Event
from nestd.providers.base import HISTORY_CUT, ForkPoint
from nestd.sessions.history import MAX_CHARS, kept_history
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from tests.fake_provider import echoed, reply
from tests.fakes import FakeClock
from tests.session_support import Env
from tests.test_session_control import until_results

NOW = datetime(2026, 11, 8, tzinfo=UTC)


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def test_the_next_message_after_a_cut_carries_only_what_was_kept(env: Env) -> None:
    env.provider.script(
        echoed("acp", reply("one", "acp-1")),
        echoed("acp", reply("two", "acp-1")),
        reply("three", "acp-2"),
    )
    env.provider.fork_points = {("acp-1", "acp"): ForkPoint(HISTORY_CUT)}
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "second", [])
    await until_results(env, created.id, 2)
    events = await env.bus.session_events(created.id)
    second = [e.id for e in events if e.type == types.SESSION_USER_MESSAGE][1]
    assert second is not None

    await env.manager.rewind(created.id, second, dry_run=False, restore="conversation")
    await env.manager.send(created.id, "instead", [])
    await until_results(env, created.id, 2)

    sent = env.provider.runs[-1].inputs[-1].text
    assert sent.startswith("This conversation continues an earlier one")
    assert "User: first" in sent
    assert "Agent: one" in sent
    assert "second" not in sent
    assert "two" not in sent
    assert sent.endswith("\n\ninstead")
    # The new engine session is the chat's once it has the message.
    session = await env.store.get(created.id)
    assert (session.provider_session_id, session.fork_at) == ("acp-2", None)


def test_a_long_history_keeps_the_latest_part() -> None:
    def said(number: int) -> Event:
        payload: dict[str, JsonValue] = {"text": f"message {number} " + "x" * 1000}
        return Event(
            id=number, ts=NOW, session_id="s", type=types.SESSION_USER_MESSAGE, payload=payload
        )

    kept = kept_history([said(n) for n in range(200)])

    assert kept is not None
    assert len(kept) < MAX_CHARS + 1000
    assert "message 199 " in kept
    assert "message 0 " not in kept
    assert kept_history([]) is None
