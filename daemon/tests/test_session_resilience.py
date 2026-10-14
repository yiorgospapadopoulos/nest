"""A crashed run leaves no stale state, and failing bookkeeping never ends a healthy run."""

import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.providers.base import McpServer, ResultInfo
from nestd.sessions import turns
from nestd.sessions.models import Session, SessionState, UpdateSession
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import background, crash, reply
from tests.fakes import FakeClock
from tests.recording_hooks import RecordingHooks
from tests.session_support import Env
from tests.test_session_control import until_results


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def test_a_crash_clears_the_background_count_so_bypass_can_reopen(env: Env) -> None:
    env.provider.script(background(1, crash("gone")), reply("back"), reply("in bypass"))
    created = await env.create()
    await env.reach(created.id, SessionState.FAILED)
    await env.manager.send(created.id, "still there?", [])
    await until_results(env, created.id, 1)

    await env.manager.update(created.id, UpdateSession(permission_mode="bypassPermissions"))
    await env.manager.send(created.id, "go on", [])
    await until_results(env, created.id, 2)

    first, second, third = env.provider.runs
    assert first.closed is True
    assert second.closed is True
    assert third.spec.permission_mode == "bypassPermissions"


async def test_a_crash_clears_the_background_count_so_the_next_run_idles_out(env: Env) -> None:
    env.manager = env.build(timedelta(milliseconds=10))
    env.provider.script(background(1, crash("gone")), reply("back"))
    created = await env.create()
    await env.reach(created.id, SessionState.FAILED)

    await env.manager.send(created.id, "still there?", [])
    await until_results(env, created.id, 1)

    await until(lambda: env.provider.runs[1].closed)


class FailingHooks(RecordingHooks):
    """Hooks whose named methods raise, as a broken tracker or notifier would."""

    def __init__(self, *failing: str) -> None:
        super().__init__()
        self.failing = set(failing)

    def check(self, name: str) -> None:
        if name in self.failing:
            raise RuntimeError(f"{name} broke")

    async def state_changed(self, session: Session) -> None:
        await super().state_changed(session)
        self.check("state_changed")

    async def message(self, session_id: str) -> None:
        await super().message(session_id)
        self.check("message")

    async def turn_result(self, session_id: str, info: ResultInfo) -> None:
        await super().turn_result(session_id, info)
        self.check("turn_result")

    async def connectors_reported(self, session_id: str, servers: list[McpServer]) -> None:
        await super().connectors_reported(session_id, servers)
        self.check("connectors_reported")


@pytest.mark.parametrize(
    ("failing", "kind"),
    [
        ("state_changed", "the state hooks"),
        ("message", "the message hooks"),
        ("turn_result", "the turn result hooks"),
        ("connectors_reported", "the connector report"),
    ],
)
async def test_failing_hooks_never_end_the_run(
    env: Env, caplog: pytest.LogCaptureFixture, failing: str, kind: str
) -> None:
    env.hooks = FailingHooks(failing)
    env.manager = env.build(timedelta(hours=1))
    env.provider.script(reply("one"), reply("two"))

    with caplog.at_level(logging.WARNING):
        created = await env.create()
        await until_results(env, created.id, 1)
        await env.manager.send(created.id, "and then?", [])
        await until_results(env, created.id, 2)

    (run,) = env.provider.runs
    assert run.closed is False
    assert [item.text for item in run.inputs][1:] == ["and then?"]
    assert "failed" not in await env.states(created.id)
    assert f"{kind} of session {created.id} failed (RuntimeError: {failing} broke)" in caplog.text


async def test_a_failing_git_audit_still_ends_the_turn_and_keeps_the_run(
    env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object) -> object:
        raise OSError("refs unreadable")

    monkeypatch.setattr(turns, "changed_refs", broken)
    env.provider.script(reply("one"), reply("two"))

    with caplog.at_level(logging.WARNING):
        created = await env.create()
        await until_results(env, created.id, 1)
        await env.manager.send(created.id, "again", [])
        await until_results(env, created.id, 2)

    (run,) = env.provider.runs
    assert run.closed is False
    assert f"the git audit of session {created.id} failed (OSError: refs unreadable)" in caplog.text


async def test_an_unreadable_queue_still_ends_the_turn(
    env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PL-05: a database error while looking for queued messages never leaves it running."""

    async def broken(session_id: str) -> object:
        raise OSError("database is locked")

    env.provider.script(reply("one"))
    monkeypatch.setattr(env.queue, "messages", broken)

    with caplog.at_level(logging.WARNING):
        created = await env.create()
        idle = await env.reach(created.id, SessionState.IDLE)

    assert idle.state is SessionState.IDLE
    assert not env.manager.busy(created.id)
    assert f"reading the queue of session {created.id} failed (database is locked)" in caplog.text
