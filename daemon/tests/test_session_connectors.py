import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.providers.base import McpServer
from nestd.sessions import turns
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
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


async def test_a_slow_status_call_does_not_hold_up_the_agents_output(env: Env) -> None:
    """I-L: the status call waits for the engine's answer outside the reader of the
    agent's messages, which the engine needs read to answer it.
    """
    gate = asyncio.Event()
    env.provider.status_gate = gate
    env.provider.script(reply("ok"), reply("again"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.send(created.id, "more", [])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)
    await until(lambda: env.hooks.states.count((created.id, SessionState.IDLE)) == 2, seconds=2)
    assert env.hooks.connectors == []

    gate.set()
    await until(lambda: len(env.hooks.connectors) == 2)


async def test_stopping_drops_a_pending_status_call(env: Env) -> None:
    env.provider.status_gate = asyncio.Event()
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await until(lambda: env.provider.runs[0].status_calls == 1)

    await asyncio.wait_for(env.manager.close(created.id, remove_worktree=False), 2)

    assert env.hooks.connectors == []


async def test_a_context_report_without_an_answer_is_given_up(
    env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(turns, "CONTROL_TIMEOUT_SECONDS", 0.05)
    env.provider.context_gate = asyncio.Event()
    env.provider.script(reply("ok"))
    created = await env.create()

    with caplog.at_level(logging.WARNING):
        await env.reach(created.id, SessionState.IDLE)

    assert f"the context report of session {created.id} failed (TimeoutError" in caplog.text
