"""Who a user message comes from: the user, a pixie, or the daemon's report (B41)."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue

from harness.errors import InvalidInputError
from harness.events import types
from harness.sessions.models import CreateSession, Sender, SessionState
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, reply
from tests.fakes import FakeClock
from tests.session_support import Env

PIXIE = Sender(from_pixie="p1")
REPORT = Sender(origin="report_back")


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def senders(env: Env, session_id: str) -> list[tuple[JsonValue, JsonValue, JsonValue]]:
    return [
        (event.payload["text"], event.payload["from_pixie"], event.payload["origin"])
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_USER_MESSAGE
    ]


async def test_a_user_message_says_it_comes_from_the_user(env: Env) -> None:
    env.provider.script(reply("done"))
    created = await env.create("Fix it")
    await env.reach(created.id, SessionState.IDLE)

    assert await senders(env, created.id) == [("Fix it", None, None)]


async def test_a_message_sent_by_a_pixie_records_it(env: Env) -> None:
    env.provider.script(reply("one"), reply("two"))
    created = await env.create("Fix it")
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.send(created.id, "Also the tests", [], sender=PIXIE)
    await until(lambda: len(env.provider.runs[0].inputs) == 2)

    assert (await senders(env, created.id))[-1] == ("Also the tests", "p1", None)


async def test_a_queued_message_keeps_its_sender_and_hides_it_from_the_queue(env: Env) -> None:
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("first")(run)

    env.provider.script(slow, reply("second"), reply("third"))
    created = await env.create("Fix it")
    await env.reach(created.id, SessionState.RUNNING)

    queued = await env.manager.send(created.id, "from the pixie", [], sender=PIXIE)
    await env.manager.send(created.id, "report", [], sender=REPORT)
    gate.set()
    await until(lambda: len(env.provider.runs[0].inputs) == 3)

    assert queued.queued_message is not None
    assert "from_pixie" not in queued.queued_message.model_dump()
    assert (await senders(env, created.id))[1:] == [
        ("from the pixie", "p1", None),
        ("report", None, "report_back"),
    ]


async def test_a_nudge_from_a_pixie_records_it(env: Env) -> None:
    started = asyncio.Event()

    async def long(run: FakeRun) -> None:
        started.set()
        await run.interrupted.wait()
        await reply("stopped")(run)

    env.provider.script(long, reply("again"))
    created = await env.create("Fix it")
    await started.wait()

    await env.manager.send(created.id, "You seem stuck", [], interrupt=True, sender=PIXIE)
    await until(lambda: len(env.provider.runs[0].inputs) == 2)

    assert (await senders(env, created.id))[-1] == ("You seem stuck", "p1", None)


async def test_a_chat_a_pixie_starts_records_it_on_the_session_and_first_message(
    env: Env,
) -> None:
    env.provider.script(reply("done"))
    request = CreateSession(repo="repo", prompt="List the files", mode="worktree")

    created = await env.manager.create(request, started_by_pixie="p1", pixie_batch="b1")
    await env.reach(created.id, SessionState.IDLE)
    stored = await env.store.get(created.id)

    assert (stored.started_by_pixie, stored.pixie_batch) == ("p1", "b1")
    assert stored.worktree_path is not None
    assert await senders(env, created.id) == [("List the files", "p1", None)]


async def test_a_pixie_cannot_start_a_chat_in_a_plain_folder(env: Env, tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    await env.repos.register(folder)
    request = CreateSession(repo="notes", prompt="Tidy up", mode="worktree")

    with pytest.raises(InvalidInputError, match="notes is not a git repository"):
        await env.manager.create(request, started_by_pixie="p1", pixie_batch="b1")
    assert await env.manager.list_sessions("notes") == []
