"""B91: a chat runs on the engine it asks for, Claude by default or Codex."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.artifacts.tools import ARTIFACT_NOTE
from nestd.errors import InvalidInputError
from nestd.providers.base import ModelOption
from nestd.providers.codex import CODEX_UNSUPPORTED, CodexNotSignedInError
from nestd.sessions.engines import Engine, Engines
from nestd.sessions.errors import UnsupportedFeatureError
from nestd.sessions.models import CreateSession, NewSession, SessionState, UpdateSession
from nestd.sessions.turns import CODEX_GUARDED_PROMPT, CODEX_PLAIN_FOLDER_PROMPT, CODEX_PROMPT
from nestd.storage.db import Database
from tests.fake_provider import FakeProvider, reply
from tests.fakes import FakeClock
from tests.session_support import Env

CODEX_MODELS = [
    ModelOption(
        value="default",
        display_name="Default",
        description="",
        effort_levels=["low", "high"],
        supports_effort=True,
        supports_auto_mode=True,
    ),
    ModelOption(value="gpt-5.5", display_name="GPT-5.5", description=""),
]


class Codex:
    def __init__(self) -> None:
        self.provider = FakeProvider()
        self.provider.name = "codex"  # type: ignore[misc]
        self.provider.unsupported = CODEX_UNSUPPORTED  # type: ignore[misc]
        self.signed_in = True
        self.models: list[ModelOption] | None = CODEX_MODELS

    async def find(self, model: str | None) -> ModelOption | None:
        value = model or "default"
        return next((m for m in self.models or [] if m.value == value), None)

    async def ready(self) -> None:
        if not self.signed_in:
            raise CodexNotSignedInError

    def engine(self) -> Engine:
        return Engine(self.provider, self.find, self.ready)


@pytest.fixture
async def codex() -> Codex:
    return Codex()


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock, codex: Codex) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.manager = environment.build(timedelta(hours=1), engines=[codex.engine()])
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def test_a_codex_chat_runs_on_codex_without_claudes_defaults(env: Env, codex: Codex) -> None:
    codex.provider.script(reply("hi", provider_session_id="thread-1"))

    created = await env.create(provider="codex", mode="in_place")
    idle = await env.reach(created.id, SessionState.IDLE)

    assert (created.provider, created.model, created.effort) == ("codex", None, None)
    assert created.permission_mode == "acceptEdits"
    assert not created.follows_claude_code_mode
    assert env.provider.runs == []
    [run] = codex.provider.runs
    assert run.spec.system_prompt_append == CODEX_PROMPT
    assert run.spec.subagents == {}
    assert run.spec.nest_tools == ()
    assert idle.provider_session_id == "thread-1"


async def test_a_chat_without_a_provider_stays_on_the_default_engine(
    env: Env, codex: Codex
) -> None:
    env.provider.script(reply("hi"))

    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)

    assert (created.provider, created.model) == ("fake", "claude-sonnet-5")
    assert codex.provider.runs == []
    assert len(env.provider.runs) == 1


async def test_a_codex_chats_model_and_effort_are_checked_against_codexs_list(
    env: Env, codex: Codex
) -> None:
    codex.provider.script(reply("hi"))

    with pytest.raises(InvalidInputError, match="does not take a thinking level"):
        await env.create(provider="codex", model="gpt-5.5", effort="high")
    created = await env.create(provider="codex", effort="high", permission_mode="auto")

    assert (created.effort, created.permission_mode) == ("high", "auto")


async def test_an_unknown_provider_is_refused(env: Env) -> None:
    with pytest.raises(InvalidInputError, match="unknown provider 'gemini'"):
        await env.create(provider="gemini")


async def test_codex_without_a_login_refuses_new_chats_and_messages(env: Env, codex: Codex) -> None:
    codex.provider.script(reply("hi"))
    created = await env.create(provider="codex")
    await env.reach(created.id, SessionState.IDLE)
    codex.signed_in = False

    with pytest.raises(CodexNotSignedInError):
        await env.create(provider="codex")
    with pytest.raises(CodexNotSignedInError):
        await env.manager.send(created.id, "more", [])

    assert len(await env.manager.list_sessions()) == 1


async def test_claude_only_operations_are_refused_on_a_codex_chat(env: Env, codex: Codex) -> None:
    codex.provider.script(reply("hi"))
    created = await env.create(provider="codex")
    await env.reach(created.id, SessionState.IDLE)

    with pytest.raises(UnsupportedFeatureError, match="cannot be rewound") as rewound:
        await env.manager.rewind(created.id, 1, dry_run=True)
    with pytest.raises(UnsupportedFeatureError, match="cannot be forked"):
        await env.manager.fork(created.id, 1)
    with pytest.raises(UnsupportedFeatureError, match="single background task"):
        await env.manager.stop_task(created.id, "task-1")

    assert rewound.value.payload() == {
        "detail": "A Codex chat cannot be rewound.",
        "code": "unsupported_feature",
        "provider": "codex",
        "feature": "rewind",
    }


async def test_a_codex_chats_new_model_is_checked_against_codexs_list(
    env: Env, codex: Codex
) -> None:
    codex.provider.script(reply("hi"))
    created = await env.create(provider="codex", permission_mode="auto")
    await env.reach(created.id, SessionState.IDLE)
    codex.models = [*CODEX_MODELS[:1], CODEX_MODELS[1].model_copy(update={"value": "plain"})]

    updated = await env.manager.update(created.id, UpdateSession(model="plain"))

    # Moved to a model without Auto, it asks again (BUG-86), by Codex's list.
    assert (updated.model, updated.permission_mode) == ("plain", "default")


async def test_codex_prompts_leave_out_claudes_tools(env: Env, codex: Codex) -> None:
    codex.provider.script(reply("hi"), reply("hi"))
    plain = env.repo_path.parent / "plain"
    plain.mkdir()
    await env.repos.register(plain)
    in_folder = await env.manager.create(CreateSession(repo="plain", prompt="Hi", provider="codex"))
    started = await env.manager.create(
        CreateSession(repo="repo", prompt="Hi", provider="codex", mode="in_place"),
        started_by_pixie="p1",
    )
    await env.reach(in_folder.id, SessionState.IDLE)
    await env.reach(started.id, SessionState.IDLE)

    prompts = {run.spec.system_prompt_append for run in codex.provider.runs}
    assert prompts == {CODEX_PLAIN_FOLDER_PROMPT, CODEX_GUARDED_PROMPT}
    # Codex has no task list, but Nest's artifact tools (B91 stage 2).
    for prompt in prompts:
        assert prompt is not None
        assert "TaskCreate" not in prompt
        assert prompt.endswith(ARTIFACT_NOTE)


def test_engines_by_name_and_by_session() -> None:
    claude = FakeProvider()
    codex = Codex()
    engines = Engines(Engine(claude), [codex.engine()])

    assert engines.named(None).provider is claude
    assert engines.named("codex").provider is codex.provider
    assert engines.default.supports("rewind")
    engines.default.require("rewind")
    assert not engines.named("codex").supports("rewind")

    def session(provider: str) -> NewSession:
        return NewSession(
            repo="r",
            title="t",
            prompt="p",
            mode="in_place",
            cwd=None,
            model=None,
            effort=None,
            permission_mode="default",
            provider=provider,
        )

    assert engines.of(session("codex")).provider is codex.provider
    # An engine not set up here, such as a chat from another setup, runs on the default.
    assert engines.of(session("gemini")).provider is claude
