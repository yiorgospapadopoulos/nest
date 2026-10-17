"""Chats run with the pixies as subagents, and team mentions reach the agent (B40, B41)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.events import types
from nestd.providers.base import CallRules, Subagent
from nestd.sessions.extras import RunExtras
from nestd.sessions.models import NewSession, Session, SessionState
from nestd.sessions.subagents import ChatAgents, TeamCall
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, background, reply
from tests.fakes import FakeClock
from tests.session_support import Env

TESTER = Subagent(description="Tester", prompt="You test.", permission_mode="default")
QA = TeamCall("qa", "\n\n(call the qa team)")
RULES = CallRules(frozenset({"tester"}), frozenset({"tester"}))


class Source:
    """The pixies as the chat would get them now; tests change them between messages."""

    def __init__(self) -> None:
        self.agents = ChatAgents({"tester": TESTER}, (QA,), rules=RULES)
        self.asked: list[str] = []

    async def __call__(self, session: NewSession) -> ChatAgents:
        self.asked.append(session.repo)
        return self.agents


async def no_extras(session: Session) -> RunExtras:
    return RunExtras(system_prompt="pixie", extra_dirs=(), tools=(), write_root=None)


@pytest.fixture
def source() -> Source:
    return Source()


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock, source: Source) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.manager = environment.build(timedelta(hours=1), no_extras, source)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def results(env: Env, session_id: str, count: int) -> None:
    async def done() -> bool:
        events = await env.bus.session_events(session_id)
        states = [e.payload["state"] for e in events if e.type == types.SESSION_STATE]
        finished = [e for e in events if e.type == types.SESSION_RESULT]
        return len(finished) == count and states[-1] == "idle"

    await until(done)


async def user_texts(env: Env, session_id: str) -> list[str]:
    events = await env.bus.session_events(session_id)
    return [str(e.payload["text"]) for e in events if e.type == types.SESSION_USER_MESSAGE]


async def test_a_project_chat_runs_with_the_pixies_as_subagents(env: Env) -> None:
    env.provider.script(reply("hi"))
    session = await env.create(prompt="Fix it")
    await results(env, session.id, 1)

    assert dict(env.provider.runs[0].spec.subagents) == {"tester": TESTER}
    # Who may call which pixie goes with them (B70).
    assert env.provider.runs[0].spec.call_rules is RULES


async def test_a_team_mention_reaches_the_agent_but_not_the_transcript(env: Env) -> None:
    env.provider.script(reply("hi"), reply("again"))
    session = await env.create(prompt="@qa review this")
    await results(env, session.id, 1)

    await env.manager.send(session.id, "thanks @qa.", [])
    await results(env, session.id, 2)

    sent = [user_input.text for user_input in env.provider.runs[0].inputs]
    assert sent == ["@qa review this\n\n(call the qa team)", "thanks @qa.\n\n(call the qa team)"]
    assert await user_texts(env, session.id) == ["@qa review this", "thanks @qa."]
    assert (await env.store.get(session.id)).prompt == "@qa review this"


async def test_a_changed_set_opens_a_fresh_run_that_resumes(env: Env, source: Source) -> None:
    env.provider.script(reply("hi"), reply("same run"), reply("new run"))
    session = await env.create()
    await results(env, session.id, 1)

    # Asked again for the same set: the run stays.
    await env.manager.send(session.id, "more", [])
    await results(env, session.id, 2)
    source.agents = ChatAgents({"tester": TESTER})
    await env.manager.send(session.id, "@qa now?", [])
    await results(env, session.id, 3)

    first, second = env.provider.runs
    assert len(first.inputs) == 2
    assert first.closed is True
    assert second.spec.resume_id == "sdk-1"
    assert dict(second.spec.subagents) == {"tester": TESTER}
    # The team is gone from this run: its mention is sent as typed.
    assert [i.text for i in second.inputs] == ["@qa now?"]


async def test_a_change_during_a_turn_waits_for_the_turn(env: Env, source: Source) -> None:
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("first")(run)

    env.provider.script(slow, reply("second"))
    session = await env.create()
    await env.reach(session.id, SessionState.RUNNING)
    await until(lambda: bool(env.provider.runs and env.provider.runs[0].inputs))

    source.agents = ChatAgents()
    queued = await env.manager.send(session.id, "next", [])
    assert queued.queued_message is not None
    assert env.provider.runs[0].closed is False
    gate.set()
    await results(env, session.id, 2)

    first, second = env.provider.runs
    assert len(first.inputs) == 1
    assert dict(second.spec.subagents) == {}


async def test_background_tasks_keep_the_run_and_its_set(env: Env, source: Source) -> None:
    env.provider.script(background(1, reply("started")), reply("two"))
    session = await env.create()
    await results(env, session.id, 1)

    source.agents = ChatAgents()
    await env.manager.send(session.id, "@qa how is it going?", [])
    await results(env, session.id, 2)

    assert len(env.provider.runs) == 1
    # The run still has the team it opened with.
    assert env.provider.runs[0].inputs[1].text == "@qa how is it going?\n\n(call the qa team)"


async def test_a_pixie_chat_runs_with_the_subagents_its_source_gives(
    env: Env, source: Source
) -> None:
    env.provider.script(reply("hi"))
    await env.db.execute(
        "INSERT INTO pixies (id, slug, name, mascot, color, permission_mode,"
        " autonomy, project_access, skills, can_call, position, created_at, updated_at)"
        " VALUES ('p1', 't', 'T', 'sprout', '#000000', 'default', 'observe', 'none',"
        " '[]', '[]', 0, 'x', 'x')"
    )
    workdir = env.paths.data_dir / "pixies" / "p1" / "workdir"
    workdir.mkdir(parents=True)
    session = await env.manager.create_pixie_chat(
        pixie_id="p1",
        cwd=workdir,
        prompt="@qa hello",
        title="T",
        model=None,
        effort=None,
        permission_mode="default",
        attachment_ids=[],
    )
    await results(env, session.id, 1)

    # Which pixies a pixie chat gets is the source's choice (B41).
    assert source.asked == [session.repo]
    assert dict(env.provider.runs[0].spec.subagents) == {"tester": TESTER}
