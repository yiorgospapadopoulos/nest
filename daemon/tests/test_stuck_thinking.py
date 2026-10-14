"""BUG-91: thinking that was never reported stopped does not hide a silent turn."""

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.storage.db import Database
from tests.fakes import FakeClock
from tests.test_stuck_watcher import Env


@pytest.fixture
def env(db: Database, clock: FakeClock) -> Env:
    return Env(db, clock)


@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        (types.SESSION_NOTICE, {"kind": "api_retry", "text": "API error, retrying"}),
        (types.SESSION_DELTA, {"text": "Done thinking"}),
        (types.SESSION_MESSAGE, {"blocks": [], "parent_tool_use_id": None}),
    ],
)
async def test_output_after_thinking_ends_it(
    env: Env, event_type: str, payload: dict[str, JsonValue]
) -> None:
    session = await env.running()
    await env.ephemeral(session, types.SESSION_THINKING, {"active": True})
    await env.wait(1)

    await env.send(session, event_type, payload)
    await env.wait(10)

    assert await env.flags(session) == [("stuck", "silent")]


async def test_a_subagents_message_does_not_end_the_main_agents_thinking(env: Env) -> None:
    session = await env.running()
    await env.ephemeral(session, types.SESSION_THINKING, {"active": True})

    await env.send(session, types.SESSION_MESSAGE, {"blocks": [], "parent_tool_use_id": "t1"})
    await env.wait(30)

    assert await env.flags(session) == []
