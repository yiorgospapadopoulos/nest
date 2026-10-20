"""BUG-86: Auto mode only on the models that take it, for new chats and model changes."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.errors import InvalidInputError
from nestd.events import types
from nestd.providers.base import ModelOption
from nestd.sessions.models import SessionState, UpdateSession
from nestd.storage.db import Database
from tests.fake_provider import reply, switched
from tests.fakes import FakeClock
from tests.session_support import DEFAULTS, Env

SONNET = ModelOption(
    value="claude-sonnet-5",
    display_name="Sonnet",
    description="",
    effort_levels=["medium"],
    supports_effort=True,
    supports_auto_mode=True,
)
HAIKU = ModelOption(
    value="haiku",
    display_name="Haiku",
    description="",
    effort_levels=[],
    supports_effort=False,
    supports_auto_mode=False,
)


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.defaults = DEFAULTS.model_copy(update={"permission_mode": "auto"})
    environment.models = [SONNET, HAIKU]
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def updates(env: Env, session_id: str) -> list[object]:
    return [
        event.payload["changes"]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_UPDATED
    ]


async def test_a_default_auto_the_model_does_not_take_is_dropped_for_a_new_chat(env: Env) -> None:
    env.provider.script(reply("ok"))

    created = await env.create(model="haiku", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    # As with no default: the chat asks (B94), and Nest passes that mode.
    assert (created.permission_mode, created.follows_claude_code_mode) == ("default", False)
    assert env.provider.runs[0].spec.permission_mode == "default"


async def test_a_default_auto_stays_for_a_model_that_takes_it(env: Env) -> None:
    env.provider.script(reply("ok"))

    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    assert (created.permission_mode, created.follows_claude_code_mode) == ("auto", False)
    assert env.provider.runs[0].spec.permission_mode == "auto"


async def test_asking_for_auto_on_a_model_without_it_is_still_refused(env: Env) -> None:
    with pytest.raises(InvalidInputError, match="Haiku does not support Auto mode"):
        await env.create(model="haiku", permission_mode="auto", mode="in_place")


async def test_switching_an_auto_chat_to_a_model_without_auto_asks_again(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    updated = await env.manager.update(created.id, UpdateSession(model="haiku"))

    assert (updated.model, updated.permission_mode) == ("haiku", "default")
    assert updated.follows_claude_code_mode is False
    assert await updates(env, created.id) == [{"model": "haiku", "permission_mode": "default"}]
    assert env.provider.runs[0].calls == [
        ("set_model", "haiku"),
        ("set_permission_mode", "default"),
    ]


async def test_auto_with_a_model_without_it_in_one_change_is_refused(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    with pytest.raises(InvalidInputError, match="Haiku does not support Auto mode"):
        await env.manager.update(created.id, UpdateSession(model="haiku", permission_mode="auto"))

    assert (await env.store.get(created.id)).model == "claude-sonnet-5"


async def test_auto_reported_by_claude_code_falls_back_on_a_model_change(env: Env) -> None:
    """A chat that followed Claude Code's own mode until it reported Auto."""
    env.defaults = DEFAULTS.model_copy(update={"permission_mode": None})
    env.provider.script(switched("auto", reply("ok")))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    updated = await env.manager.update(created.id, UpdateSession(model="haiku"))

    assert (updated.model, updated.permission_mode) == ("haiku", "default")


async def test_a_chat_following_claude_codes_mode_keeps_following(env: Env) -> None:
    """A chat from before B94 that follows Claude Code's own mode."""
    env.defaults = DEFAULTS.model_copy(update={"permission_mode": None})
    env.provider.script(reply("ok"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.store.update(created.id, follows_claude_code_mode=True)

    updated = await env.manager.update(created.id, UpdateSession(model="haiku"))

    assert (updated.permission_mode, updated.follows_claude_code_mode) == ("default", True)
    assert env.provider.runs[0].calls == [("set_model", "haiku")]


async def test_other_modes_stay_on_a_model_change(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(permission_mode="plan", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    updated = await env.manager.update(created.id, UpdateSession(model="haiku"))

    assert updated.permission_mode == "plan"
    assert env.provider.runs[0].calls == [("set_model", "haiku")]


async def test_auto_is_kept_while_the_model_list_is_unknown(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    env.models = None

    updated = await env.manager.update(created.id, UpdateSession(model="haiku"))

    assert updated.permission_mode == "auto"
