from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.providers.base import McpServer
from harness.sessions.models import SessionState
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import loaded, reply, stopped_then_result
from tests.fakes import FakeClock
from tests.session_support import Env


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def test_each_turn_end_reports_the_settled_connector_statuses(env: Env) -> None:
    pending = [McpServer("claude.ai Gmail", "pending")]
    settled = [McpServer("claude.ai Gmail", "connected"), McpServer("db", "failed", "ENOENT")]
    env.provider.statuses = settled
    env.provider.script(loaded(pending, reply("ok")))

    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await until(lambda: len(env.hooks.connectors) == 2)

    assert env.hooks.connectors == [(created.id, pending), (created.id, settled)]
    assert env.provider.runs[0].status_calls == 1


async def test_a_failing_status_call_never_breaks_the_turn(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.provider.status_error = RuntimeError("control request timed out")
    env.provider.script(reply("ok"), reply("again"))

    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "more", [])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)
    session = await env.reach(created.id, SessionState.IDLE)

    assert session.last_error is None
    assert env.hooks.connectors == []
    assert "control request timed out" in caplog.text


async def test_no_status_call_once_the_run_is_gone(env: Env) -> None:
    env.provider.script(stopped_then_result())

    created = await env.create()
    await until(lambda: (created.id, SessionState.IDLE) in env.hooks.states)

    assert env.provider.runs[0].status_calls == 0
    assert env.hooks.connectors == []
