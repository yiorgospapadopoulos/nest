"""IMP-06: Claude Code's own permission mode, and `auto` for the models that support it."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from harness.errors import InvalidInputError
from harness.events import types
from harness.providers.base import ModelOption
from harness.sessions.models import SessionState, UpdateSession
from harness.storage.db import Database
from tests.fake_provider import reply, switched
from tests.fakes import FakeClock
from tests.session_support import DEFAULTS, Env
from tests.test_session_control import until_results


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.defaults = DEFAULTS.model_copy(update={"permission_mode": None})
    await environment.register()
    yield environment
    await environment.manager.shutdown()


def model(supports_auto: bool) -> ModelOption:
    return ModelOption(
        value="claude-sonnet-5",
        display_name="Sonnet",
        description="",
        effort_levels=["medium"],
        supports_effort=True,
        supports_auto_mode=supports_auto,
    )


async def updates(env: Env, session_id: str) -> list[object]:
    return [
        event.payload["changes"]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_UPDATED
    ]


async def test_without_a_chosen_mode_the_run_opens_in_claude_codes_own(env: Env) -> None:
    env.provider.script(switched("auto", reply("ok")), reply("again"))

    created = await env.create()
    idle = await env.reach(created.id, SessionState.IDLE)

    # Until the engine says, the session shows the placeholder and follows Claude Code.
    assert (created.permission_mode, created.follows_claude_code_mode) == ("default", True)
    assert env.provider.runs[0].spec.permission_mode is None
    assert (idle.permission_mode, idle.follows_claude_code_mode) == ("auto", False)
    assert await updates(env, created.id) == [
        {"permission_mode": "auto", "follows_claude_code_mode": False}
    ]
    # Harness never sent the run a mode of its own.
    assert env.provider.runs[0].calls == []
    # A reopened run continues in the mode the engine reported.
    await env.manager.shutdown()
    env.manager = env.build(timedelta(hours=1))
    await env.manager.send(created.id, "go on", [])
    await until_results(env, created.id, 2)
    assert env.provider.runs[1].spec.permission_mode == "auto"


async def test_the_reported_mode_ends_following_even_when_it_is_the_placeholder(
    env: Env,
) -> None:
    env.provider.script(switched("default", reply("ok")))

    created = await env.create()
    idle = await env.reach(created.id, SessionState.IDLE)

    assert (idle.permission_mode, idle.follows_claude_code_mode) == ("default", False)
    assert await updates(env, created.id) == [{"follows_claude_code_mode": False}]


async def test_bypass_reported_by_the_engine_needs_no_new_run(env: Env) -> None:
    """A run Claude Code opened in bypass (its `defaultMode`) may switch in and out live."""
    env.provider.script(switched("bypassPermissions", reply("ok")), reply("two"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.update(created.id, UpdateSession(permission_mode="default"))
    await env.manager.update(created.id, UpdateSession(permission_mode="bypassPermissions"))
    await env.manager.send(created.id, "go on", [])
    await until_results(env, created.id, 2)

    assert len(env.provider.runs) == 1
    assert env.provider.runs[0].calls == [
        ("set_permission_mode", "default"),
        ("set_permission_mode", "bypassPermissions"),
    ]


async def test_choosing_a_mode_stops_following_claude_codes_own(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    # The same value as the placeholder is still a choice, sent to the run.
    chosen = await env.manager.update(created.id, UpdateSession(permission_mode="default"))

    assert (chosen.permission_mode, chosen.follows_claude_code_mode) == ("default", False)
    assert env.provider.runs[0].calls == [("set_permission_mode", "default")]


async def test_a_chosen_mode_is_passed_to_the_run(env: Env) -> None:
    env.provider.script(reply("ok"))

    created = await env.create(permission_mode="plan")
    await env.reach(created.id, SessionState.IDLE)

    assert (created.permission_mode, created.follows_claude_code_mode) == ("plan", False)
    assert env.provider.runs[0].spec.permission_mode == "plan"


async def test_auto_needs_a_model_that_supports_it(env: Env) -> None:
    env.models = [model(supports_auto=False)]
    env.provider.script(reply("ok"))

    with pytest.raises(InvalidInputError, match="Sonnet does not support Auto mode"):
        await env.create(permission_mode="auto")
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    with pytest.raises(InvalidInputError, match="Sonnet does not support Auto mode"):
        await env.manager.update(created.id, UpdateSession(permission_mode="auto"))
    env.models = [model(supports_auto=True)]
    updated = await env.manager.update(created.id, UpdateSession(permission_mode="auto"))

    assert updated.permission_mode == "auto"


async def test_auto_is_not_checked_while_the_model_list_is_unknown(env: Env) -> None:
    env.provider.script(reply("ok"))

    created = await env.create(permission_mode="auto")
    await env.reach(created.id, SessionState.IDLE)

    assert env.provider.runs[0].spec.permission_mode == "auto"
