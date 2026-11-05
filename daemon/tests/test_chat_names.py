"""A new chat's name waits for the engine's own, once; a chat never stays nameless (B125)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.events import types
from nestd.providers.base import RunAccount
from nestd.sessions.engines import Engine
from nestd.sessions.models import SessionState, UpdateSession
from nestd.sessions.titles import clean_name
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeProvider, FakeRun, crash, hang, reply
from tests.fakes import FakeClock
from tests.session_support import Env

QUICK = "Fix the bug"


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def small_model() -> str | None:
    return "tiny"


async def account() -> RunAccount:
    return RunAccount("second", {"HOME": "/second"})


def no_engine_names(env: Env) -> FakeProvider:
    """Chats run on an engine with no names of its own."""
    other = FakeProvider()
    other.name = "other"
    other.names_chats = False

    class Accounts:
        def active(self) -> str:
            return "second"

        async def prepare(self) -> RunAccount:
            return await account()

    env.manager = env.build(
        timedelta(hours=1),
        engines=[Engine(other, small=small_model, accounts=Accounts())],
    )
    return other


async def renamed(env: Env, session_id: str, title: str) -> None:
    async def done() -> bool:
        return (await env.store.get(session_id)).title == title

    await until(done)


async def test_the_engines_name_replaces_the_quick_name_and_reaches_clients(env: Env) -> None:
    env.provider.chat_title = "Login redirect loop"
    env.provider.script(reply("ok"))
    created = await env.create(title=None)
    assert (created.title, created.title_pending) == (QUICK, True)

    await renamed(env, created.id, "Login redirect loop")
    assert not (await env.store.get(created.id)).title_pending

    events = await env.bus.session_events(created.id)
    update = next(
        e for e in events if e.type == types.SESSION_UPDATED and "title" in str(e.payload)
    )
    assert update.payload["changes"] == {"title": "Login redirect loop", "title_pending": False}


async def test_a_name_set_by_hand_while_the_engines_name_is_on_its_way_stays(env: Env) -> None:
    env.provider.chat_title = "Login redirect loop"
    env.provider.title_gate = asyncio.Event()
    env.provider.script(identified)
    created = await env.create(title=None)
    await until_asked(env)

    await env.manager.update(created.id, UpdateSession(title="Mine"))
    env.provider.title_gate.set()
    await settled(env)

    assert (await env.store.get(created.id)).title == "Mine"


async def identified(run: FakeRun) -> None:
    await run.sink.provider_session_id("sdk-1")
    await hang()(run)


async def settled(env: Env) -> None:
    await asyncio.gather(*env.manager.namer.tasks)


async def until_asked(env: Env) -> None:
    async def asked() -> bool:
        return env.provider.title_asks > 0

    await until(asked)


async def test_a_chat_that_gets_no_name_shows_its_quick_one(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(title=None)
    await env.reach(created.id, SessionState.IDLE)
    await settled(env)

    session = await env.store.get(created.id)
    assert (session.title, session.title_pending) == (QUICK, False)
    updates = [
        e.payload["changes"]
        for e in await env.bus.session_events(created.id)
        if e.type == types.SESSION_UPDATED
    ]
    assert {"title_pending": False} in updates


async def test_no_chat_waits_for_its_name_after_a_restart(env: Env) -> None:
    env.provider.script(hang())
    created = await env.create(title=None)
    await env.manager.shutdown()
    assert (await env.store.get(created.id)).title_pending

    env.manager = env.build(timedelta(hours=1))
    await env.manager.recover()

    assert not (await env.store.get(created.id)).title_pending


async def test_a_chosen_name_is_never_replaced(env: Env) -> None:
    env.provider.chat_title = "Login redirect loop"
    env.provider.script(reply("ok"))
    created = await env.create(title="Chosen")
    assert not created.title_pending
    await env.reach(created.id, SessionState.IDLE)
    await settled(env)

    assert (await env.store.get(created.id)).title == "Chosen"
    assert env.provider.title_asks == 0


async def test_a_chat_from_before_keeps_its_name(env: Env) -> None:
    env.provider.script(reply("ok"), reply("again"))
    created = await env.create(title=None)
    await env.reach(created.id, SessionState.IDLE)
    await settled(env)
    await env.store.update(created.id, title_pending=False)
    await env.manager.shutdown()
    env.manager = env.build(timedelta(hours=1))
    env.provider.chat_title = "Login redirect loop"

    await env.manager.send(created.id, "more", [])
    await env.reach(created.id, SessionState.IDLE)
    await settled(env)

    assert (await env.store.get(created.id)).title == QUICK


async def test_a_name_comes_once_and_stays(env: Env) -> None:
    env.provider.chat_title = "First name"
    env.provider.script(reply("ok"), reply("again"))
    created = await env.create(title=None)
    await renamed(env, created.id, "First name")
    await env.reach(created.id, SessionState.IDLE)
    env.provider.chat_title = "Second name"

    await env.manager.send(created.id, "more", [])
    await env.reach(created.id, SessionState.IDLE)
    await settled(env)

    assert (await env.store.get(created.id)).title == "First name"


async def test_an_engine_without_names_gets_one_from_a_small_call_of_its_own(env: Env) -> None:
    other = no_engine_names(env)
    other.script(reply("ok"), reply('"Login redirect loop."'))
    created = await env.create(
        title=None, provider="other", prompt="Users bounce between pages\nafter login"
    )

    await renamed(env, created.id, "Login redirect loop")

    (chat, call) = other.runs
    assert call.spec.keep_history is False
    assert call.spec.model == "tiny"
    assert call.spec.account == await account()
    assert call.spec.cwd != chat.spec.cwd
    assert call.spec.resume_id is None
    assert call.spec.tools == ()
    assert call.spec.nest_tools == ()
    assert "Users bounce between pages" in call.inputs[0].text
    assert call.closed
    # Nothing of the call is in the chat's transcript, nor in what the chat's run was told.
    assert len(chat.inputs) == 1
    await env.reach(created.id, SessionState.IDLE)
    messages = [
        str(event.payload)
        for event in await env.bus.session_events(created.id)
        if event.type in (types.SESSION_USER_MESSAGE, types.SESSION_MESSAGE)
    ]
    assert not any("Login redirect loop" in message for message in messages)


async def test_a_failed_name_call_leaves_the_quick_name_and_the_chat_working(env: Env) -> None:
    other = no_engine_names(env)
    other.script(reply("ok"), crash("the engine fell over"))
    created = await env.create(title=None, provider="other")
    await env.reach(created.id, SessionState.IDLE)
    await settled(env)

    session = await env.store.get(created.id)
    assert (session.title, session.title_pending) == (QUICK, False)
    assert session.state is SessionState.IDLE


@pytest.mark.parametrize(
    ("raw", "name"),
    [
        ("Login redirect loop", "Login redirect loop"),
        ('"Login redirect loop."\n', "Login redirect loop"),
        ("**Login redirect loop**", "Login redirect loop"),
        ("\n\n# Login redirect loop\nmore text", "Login redirect loop"),
        ("  ", None),
        ('""', None),
        ("word " * 60, ("word " * 16).strip()),
    ],
)
def test_a_reply_is_cleaned_into_one_short_line(raw: str, name: str | None) -> None:
    assert clean_name(raw) == name
