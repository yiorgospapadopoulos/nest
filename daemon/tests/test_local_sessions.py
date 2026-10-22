"""B106: chats on local models run on their engine, pointed at the model's server."""

from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.local.errors import (
    LocalModelNotLoadedError,
    LocalServerDownError,
    LocalUnsupportedError,
)
from nestd.local.models import local_id
from nestd.local.run import LocalRun
from nestd.providers.base import TokenUsage
from nestd.sessions.local import NoLocalModelsError, crosses_local, require
from nestd.sessions.models import SessionState, UpdateSession
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, Turn, engine_error, reply
from tests.fakes import FakeClock
from tests.session_support import Env
from tests.test_session_engines import Codex

MODEL = "local:lm_coder"
NOT_LOADED: dict[str, JsonValue] = {
    "app": "LM Studio",
    "address": "127.0.0.1:1234",
    "model": "qwen3-coder",
}
DOWN: dict[str, JsonValue] = {"app": "Ollama", "address": "127.0.0.1:11434", "start": "ollama"}


async def results(env: Env, session_id: str, count: int) -> bool:
    return (await env.event_types(session_id)).count("session.result") == count


class FakeLocal:
    def __init__(self) -> None:
        self.running = True
        self.vision = False
        self.thinking = False
        self.engine_name = "fake"
        self.usage: list[tuple[str, TokenUsage]] = []
        # Whether the model needs loading, and whether that fails.
        self.needs_load = False
        self.load_fails = False

    async def engine(self) -> str:
        return self.engine_name

    async def require_running(self, model: str) -> None:
        if not self.running:
            raise LocalServerDownError(DOWN)

    async def run_for(self, model: str) -> LocalRun:
        return LocalRun(
            model_id=local_id(model),
            model="qwen3-coder",
            context=65536,
            vision=self.vision,
            thinking=self.thinking,
            base_url_for_claude="http://127.0.0.1:11434",
            key_for_claude="nest-local",
            base_url_for_codex="http://127.0.0.1:11434/v1",
            key_for_codex="nest-local",
        )

    async def load_model(self, model: str, notice: Callable[[str], Awaitable[None]]) -> None:
        if self.needs_load:
            await notice("Loading qwen3-coder in LM Studio")
        if self.load_fails:
            raise LocalModelNotLoadedError(NOT_LOADED, "not enough memory")

    async def down(self, model: str) -> dict[str, JsonValue] | None:
        if self.load_fails:
            return {"code": "local_model_not_loaded", "detail": "LM Studio could not", **NOT_LOADED}
        return None if self.running else {"code": "local_server_down", **DOWN}

    async def record_usage(self, model: str, tokens: TokenUsage) -> None:
        self.usage.append((model, tokens))


class Account:
    def active(self) -> str:
        return "claude-main"

    async def prepare(self) -> object:
        raise AssertionError("a local run signs in to nothing")


@pytest.fixture
def local() -> FakeLocal:
    return FakeLocal()


@pytest.fixture
async def env(
    tmp_path: Path, db: Database, clock: FakeClock, local: FakeLocal
) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.manager = environment.build(timedelta(hours=1), local=local)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def test_a_local_chat_runs_on_claude_pointed_at_the_server(
    env: Env, local: FakeLocal
) -> None:
    tokens = TokenUsage(input_tokens=1200, output_tokens=80)
    env.provider.script(reply("done", tokens=tokens))

    created = await env.create(model=MODEL, effort="high", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    assert (created.provider, created.model) == ("fake", MODEL)
    [run] = env.provider.runs
    assert run.spec.local == await local.run_for(MODEL)
    assert run.spec.model == "qwen3-coder"
    # No thinking on this model, so no level.
    assert run.spec.effort is None
    assert run.spec.account is None
    # Counted as local usage, not as the engine's.
    assert local.usage == [("lm_coder", tokens)]
    assert env.hooks.results == []


async def test_a_thinking_local_model_keeps_the_level(env: Env, local: FakeLocal) -> None:
    local.thinking = True
    env.provider.script(reply("done"))

    created = await env.create(model=MODEL, effort="high", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    assert env.provider.runs[0].spec.effort == "high"


async def test_new_local_chats_run_on_the_engine_chosen_for_them(
    tmp_path: Path, db: Database, clock: FakeClock, local: FakeLocal
) -> None:
    codex = Codex()
    # Codex is not signed in: a local chat needs no login.
    codex.signed_in = False
    local.engine_name = "codex"
    env = Env(tmp_path, db, clock)
    env.manager = env.build(timedelta(hours=1), engines=[codex.engine()], local=local)
    await env.register()
    codex.provider.script(reply("hi"))

    created = await env.create(model=MODEL, mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    assert created.provider == "codex"
    [run] = codex.provider.runs
    assert run.spec.local is not None
    await env.manager.shutdown()


async def test_a_local_model_as_the_default_stays_on_the_defaults_engine(
    env: Env, local: FakeLocal
) -> None:
    local.engine_name = "codex"  # unknown here: never asked for
    env.defaults = env.defaults.model_copy(update={"model": MODEL})
    env.provider.script(reply("hi"))

    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    assert (created.provider, created.model) == ("fake", MODEL)


async def test_a_chat_on_a_server_that_is_down_is_refused_and_kept_out(
    env: Env, local: FakeLocal
) -> None:
    local.running = False

    with pytest.raises(LocalServerDownError) as raised:
        await env.create(model=MODEL, mode="in_place")

    assert raised.value.payload() == {
        "detail": "Ollama at 127.0.0.1:11434 is not running",
        "code": "local_server_down",
        **DOWN,
    }
    assert await env.manager.list_sessions() == []


async def test_a_message_to_a_server_that_is_down_is_not_taken(env: Env, local: FakeLocal) -> None:
    env.provider.script(reply("one"))
    created = await env.create(model=MODEL, mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    local.running = False

    with pytest.raises(LocalServerDownError):
        await env.manager.send(created.id, "again", [])

    assert await env.manager.queued(created.id) == []
    assert (await env.event_types(created.id)).count("session.user_message") == 1


async def test_a_turn_cut_off_by_the_server_going_away_says_so(env: Env, local: FakeLocal) -> None:
    def server_gone(then: Turn) -> Turn:
        async def turn(run: FakeRun) -> None:
            local.running = False
            await then(run)

        return turn

    env.provider.script(server_gone(engine_error("Connection error.")))

    created = await env.create(model=MODEL, mode="in_place")
    await env.reach(created.id, SessionState.FAILED)

    [failed] = [
        event.payload
        for event in await env.bus.session_events(created.id)
        if event.type == "session.state" and event.payload["state"] == "failed"
    ]
    assert failed["error"] == "Connection error."
    assert {name: failed.get(name) for name in ("code", "app", "address", "start")} == {
        "code": "local_server_down",
        **DOWN,
    }


async def test_a_failed_turn_with_the_server_up_or_off_a_local_model_says_nothing_more(
    env: Env,
) -> None:
    env.provider.script(engine_error("Bad request."), engine_error("Overloaded."))
    local_chat = await env.create(model=MODEL, mode="in_place")
    other = await env.create(model="claude-sonnet-5", mode="in_place")
    await env.reach(local_chat.id, SessionState.FAILED)
    await env.reach(other.id, SessionState.FAILED)

    for session in (local_chat, other):
        [failed] = [
            event.payload
            for event in await env.bus.session_events(session.id)
            if event.type == "session.state" and event.payload["state"] == "failed"
        ]
        assert "code" not in failed


async def test_images_need_a_model_with_vision(env: Env, local: FakeLocal) -> None:
    image = await env.attachments.save("shot.png", b"\x89PNG", "image/png")

    with pytest.raises(LocalUnsupportedError) as raised:
        await env.create(model=MODEL, mode="in_place", attachment_ids=[image.id])

    assert raised.value.payload() == {
        "detail": (
            "This local model cannot read images. Choose a model with vision, or remove the image."
        ),
        "code": "unsupported_feature",
        "provider": "local",
        "feature": "images",
    }
    local.vision = True
    env.provider.script(reply("a cat"))
    created = await env.create(model=MODEL, mode="in_place", attachment_ids=[image.id])
    await env.reach(created.id, SessionState.IDLE)

    local.vision = False
    second = await env.attachments.save("again.png", b"\x89PNG", "image/png")
    with pytest.raises(LocalUnsupportedError):
        await env.manager.send(created.id, "and this?", [second.id])


async def test_moving_to_or_from_a_local_model_opens_a_new_run(env: Env) -> None:
    env.provider.script(reply("one"), reply("two"), reply("three"))
    created = await env.create(model="claude-sonnet-5", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    await env.manager.update(created.id, UpdateSession(model=MODEL))
    first = env.provider.runs[0]
    # The open run is not switched to a model its endpoint does not serve.
    assert ("set_model", MODEL) not in first.calls
    await env.manager.send(created.id, "now locally", [])
    await until(lambda: results(env, created.id, 2))
    await env.manager.update(created.id, UpdateSession(model="claude-opus-5"))
    await env.manager.send(created.id, "back", [])
    await until(lambda: results(env, created.id, 3))

    assert [run.spec.local is not None for run in env.provider.runs] == [False, True, False]
    assert first.closed


async def test_a_local_run_ignores_the_engines_account(
    tmp_path: Path, db: Database, clock: FakeClock, local: FakeLocal
) -> None:
    env = Env(tmp_path, db, clock)
    env.manager = env.build(timedelta(hours=1), accounts=Account(), local=local)  # type: ignore[arg-type]
    await env.register()
    env.provider.script(reply("one"), reply("two"))

    created = await env.create(model=MODEL, mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "again", [])
    await until(lambda: results(env, created.id, 2))

    # The same run takes the second message.
    assert len(env.provider.runs) == 1
    await env.manager.shutdown()


async def test_a_daemon_without_local_models_refuses_one(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    env = Env(tmp_path, db, clock)
    await env.register()

    with pytest.raises(NoLocalModelsError):
        await env.create(model=MODEL, mode="in_place")
    with pytest.raises(NoLocalModelsError):
        require(None)
    await env.manager.shutdown()


def test_a_model_change_crosses_a_local_endpoint() -> None:
    assert crosses_local("opus", MODEL)
    assert crosses_local(MODEL, "local:lm_other")
    assert not crosses_local(MODEL, MODEL)
    assert not crosses_local("opus", "sonnet")


async def test_a_model_that_must_load_says_so_in_the_chat(env: Env, local: FakeLocal) -> None:
    local.needs_load = True
    env.provider.script(reply("done"))

    created = await env.create(model=MODEL, mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    events = await env.bus.session_events(created.id)
    kinds = [event.type for event in events]
    # After the message is shown, before the agent runs.
    assert kinds.index("session.user_message") < kinds.index("session.notice")
    [notice] = [event.payload for event in events if event.type == "session.notice"]
    assert notice == {"kind": "loading_model", "text": "Loading qwen3-coder in LM Studio"}


async def test_a_model_that_cannot_load_fails_the_turn_and_keeps_the_message(
    env: Env, local: FakeLocal
) -> None:
    local.load_fails = True

    created = await env.create(model=MODEL, mode="in_place")
    await env.reach(created.id, SessionState.FAILED)

    events = await env.bus.session_events(created.id)
    assert [event.payload["text"] for event in events if event.type == "session.user_message"] == [
        "Fix the bug\nDetails here"
    ]
    [failed] = [
        event.payload
        for event in events
        if event.type == "session.state" and event.payload["state"] == "failed"
    ]
    assert {name: failed.get(name) for name in ("code", "detail", "app", "address", "model")} == {
        "code": "local_model_not_loaded",
        "detail": "LM Studio could not",
        **NOT_LOADED,
    }
    assert env.provider.runs == []
