"""The one setting for what agents may do on their own: `[limits] can_push` (D160)."""

import tomllib
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.config.loader import load_settings
from nestd.paths import AppPaths
from nestd.pixies.prompt import call_prompt, habit_system_prompt, system_prompt
from nestd.sessions.models import CreateSession, Session, SessionState
from nestd.sessions.turns import CODEX_GUARDED_PROMPT, GUARDED_PROMPT, STARTED_PROMPT
from nestd.storage.db import Database
from tests.api_client import Api, running_api, wants_loops
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.session_support import Env
from tests.test_pixie_chat_turns import create as create_pixie_chat
from tests.test_pixie_chat_turns import fixed_extras
from tests.test_pixie_prompt import PIXIE

NO_PUSH = "git push"


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.manager = environment.build(timedelta(hours=1), extras=fixed_extras)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


@pytest.fixture
async def api(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, request: pytest.FixtureRequest
) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets, loops=wants_loops(request)) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def normal_chat(env: Env) -> Session:
    env.provider.script(reply("hello"))
    created = await env.create(prompt="first", mode="in_place")
    return await env.reach(created.id, SessionState.IDLE)


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/limits/settings"), ("PUT", "/api/limits/settings")]
)
async def test_the_setting_requires_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_the_setting_is_off_until_turned_on_and_stays_on(api: Api, tmp_path: Path) -> None:
    assert (await api.http.get("/api/limits/settings")).json() == {"can_push": False}

    saved = await api.http.put("/api/limits/settings", json={"can_push": True})

    assert saved.json() == {"can_push": True}
    assert (await api.http.get("/api/limits/settings")).json() == {"can_push": True}
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    assert tomllib.loads(paths.settings_file.read_text(encoding="utf-8"))["limits"] == {
        "can_push": True
    }
    assert load_settings(paths).limits.can_push is True


async def test_a_pixie_run_is_guarded_while_the_setting_is_off(env: Env) -> None:
    env.provider.script(reply("hi", "sdk-1"))
    await create_pixie_chat(env)
    await until(lambda: len(env.provider.runs) == 1)

    spec = env.provider.runs[0].spec
    assert spec.guard_git is True
    assert spec.guard_subagents is True


async def test_with_the_setting_on_a_pixie_run_is_not_guarded(env: Env) -> None:
    env.can_push = True
    env.provider.script(reply("hi", "sdk-1"))
    await create_pixie_chat(env)
    await until(lambda: len(env.provider.runs) == 1)

    spec = env.provider.runs[0].spec
    assert spec.guard_git is False
    assert spec.guard_subagents is False


async def test_a_change_reopens_a_live_run_for_the_next_turn(env: Env) -> None:
    session = await normal_chat(env)
    assert env.provider.runs[-1].spec.guard_subagents is True

    env.can_push = True
    env.provider.script(reply("again"))
    await env.manager.send(session.id, "go on", [])
    await until(lambda: len(env.provider.runs) == 2)

    assert env.provider.runs[-1].spec.guard_subagents is False


async def test_no_change_keeps_the_live_run(env: Env) -> None:
    session = await normal_chat(env)

    env.provider.script(reply("again"))
    await env.manager.send(session.id, "go on", [])
    await until(lambda: env.hooks.states.count((session.id, SessionState.IDLE)) >= 2)

    assert len(env.provider.runs) == 1


async def test_a_chat_a_pixie_started_says_no_push_only_while_the_setting_is_off(
    env: Env,
) -> None:
    env.provider.script(reply("hi"), reply("hi"))
    request = CreateSession(repo="repo", prompt="List the files", mode="in_place")
    off = await env.manager.create(request, started_by_pixie="p1", pixie_batch="b1")
    await env.reach(off.id, SessionState.IDLE)
    env.can_push = True
    on = await env.manager.create(request, started_by_pixie="p1", pixie_batch="b2")
    await env.reach(on.id, SessionState.IDLE)

    first, second = env.provider.runs[0].spec, env.provider.runs[1].spec
    assert first.system_prompt_append is not None
    assert first.system_prompt_append.startswith(GUARDED_PROMPT)
    assert second.system_prompt_append is not None
    assert second.system_prompt_append.startswith(STARTED_PROMPT)


def test_only_the_guarded_prompts_name_pushing() -> None:
    assert NO_PUSH in GUARDED_PROMPT
    assert NO_PUSH in CODEX_GUARDED_PROMPT
    assert NO_PUSH not in STARTED_PROMPT


def test_pixie_prompts_name_pushing_while_the_setting_is_off() -> None:
    for prompt in (
        system_prompt(PIXIE, "", "", [], None),
        habit_system_prompt(PIXIE, "", "", []),
        call_prompt(PIXIE, "", "", None),
    ):
        assert NO_PUSH in prompt


def test_pixie_prompts_leave_pushing_out_with_the_setting_on() -> None:
    for prompt in (
        system_prompt(PIXIE, "", "", [], None, can_push=True),
        habit_system_prompt(PIXIE, "", "", [], can_push=True),
        call_prompt(PIXIE, "", "", None, can_push=True),
    ):
        assert NO_PUSH not in prompt
        assert "You may commit your work." in prompt
