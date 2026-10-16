"""A chat's run reports its pixie calls, and pixies tagged again get their note (B46)."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.errors import NestError
from nestd.providers.base import AgentTask, MessageBlock, Subagent, TextBlock, ToolUseBlock
from nestd.sessions.errors import PixieInTeamError
from nestd.sessions.models import NewSession
from nestd.sessions.subagents import ChatAgents, OfferedPixie, TeamCall
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, Turn, messages, reply, tasks
from tests.fakes import FakeClock
from tests.session_support import Env

SCRIBE = Subagent(description="Scribe", prompt="You write.", permission_mode="default")
BUGS = Subagent(description="Bugs", prompt="You find bugs.", permission_mode="default")
AGENTS = ChatAgents(
    {"scribe": SCRIBE, "bugs": BUGS},
    (TeamCall("qa", " [call qa]"),),
    {
        "scribe": OfferedPixie("p1", "scribe", "Scribe"),
        "bugs": OfferedPixie("p2", "bugs", "Bugs", "t1", "qa"),
    },
)


class Calls:
    """Records what the run reports; its note names the text it was asked about."""

    def __init__(self) -> None:
        self.seen: list[tuple[str, object]] = []
        self.fail = False

    async def note(self, session_id: str, agents: ChatAgents, text: str) -> str:
        if self.fail:
            raise RuntimeError("database locked")
        return f" [note for {text}]"

    async def message(
        self, session_id: str, agents: ChatAgents, blocks: list[MessageBlock]
    ) -> None:
        assert agents is AGENTS
        self.seen.append(("message", blocks))

    async def task(self, session_id: str, agents: ChatAgents, update: AgentTask) -> None:
        self.seen.append(("task", update.task_id))


async def source(session: NewSession) -> ChatAgents:
    return AGENTS


@pytest.fixture
def calls() -> Calls:
    return Calls()


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock, calls: Calls) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.manager = environment.build(timedelta(hours=1), None, source, calls)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def idle(env: Env, session_id: str, count: int) -> None:
    async def done() -> bool:
        events = await env.bus.session_events(session_id)
        states = [e.payload["state"] for e in events if e.type == "session.state"]
        return [e.type for e in events].count("session.result") == count and states[-1] == "idle"

    await until(done)


async def test_the_run_reports_main_messages_and_tasks(env: Env, calls: Calls) -> None:
    call = ToolUseBlock(id="a1", name="Agent", input={"subagent_type": "scribe"})
    env.provider.script(
        messages(
            ([call], None),
            ([TextBlock(text="inside")], "a1"),
            then=tasks(AgentTask(task_id="ag1", phase="started"), then=reply("done")),
        )
    )
    session = await env.create(prompt="@scribe go", mode="in_place")
    await idle(env, session.id, 1)

    assert calls.seen == [
        ("message", [call]),
        ("task", "ag1"),
        ("message", [TextBlock(text="done")]),
    ]
    assert [i.text for i in env.provider.runs[0].inputs] == ["@scribe go [note for @scribe go]"]


async def test_a_message_written_into_the_turn_gets_its_note(env: Env) -> None:
    env.provider.steering = True
    gate = asyncio.Event()

    def held(then: Turn) -> Turn:
        async def turn(run: FakeRun) -> None:
            await gate.wait()
            await run.read_steered()
            await then(run)

        return turn

    env.provider.script(held(reply("both")))
    session = await env.create(prompt="first", mode="in_place")
    await until(lambda: bool(env.provider.runs and env.provider.runs[0].inputs))
    await until(lambda: env.manager._live[session.id].task is None)  # pyright: ignore[reportPrivateUsage]

    await env.manager.send(session.id, "@qa too", [])
    ((_, steered),) = env.provider.runs[0].steered
    gate.set()
    await idle(env, session.id, 1)

    assert steered.text == "@qa too [call qa] [note for @qa too]"


async def test_a_failing_note_still_sends_the_message(env: Env, calls: Calls) -> None:
    calls.fail = True
    env.provider.script(reply("hi"))
    session = await env.create(prompt="@qa go", mode="in_place")
    await idle(env, session.id, 1)

    assert [i.text for i in env.provider.runs[0].inputs] == ["@qa go [call qa]"]


@pytest.mark.parametrize("prompt", ["@bugs look", "first, then @bugs."])
async def test_a_team_member_alone_is_refused(env: Env, prompt: str) -> None:
    with pytest.raises(PixieInTeamError) as refused:
        await env.create(prompt=prompt, mode="in_place")

    assert str(refused.value) == "Bugs is in @qa; call the team or a solo copy"
    assert refused.value.payload() == {
        "detail": "Bugs is in @qa; call the team or a solo copy",
        "code": "pixie_in_team",
    }
    assert isinstance(refused.value, NestError)
    assert refused.value.status_code == 422
    assert await env.store.list_sessions() == []


async def test_a_member_alone_is_refused_in_every_later_message(env: Env) -> None:
    gate = asyncio.Event()

    async def slow(run: FakeRun) -> None:
        await gate.wait()
        await reply("first")(run)

    env.provider.script(slow, reply("second"))
    session = await env.create(prompt="@qa go", mode="in_place")
    await until(lambda: bool(env.provider.runs and env.provider.runs[0].inputs))

    # While a turn runs (queued) and once it is idle.
    with pytest.raises(PixieInTeamError):
        await env.manager.send(session.id, "@bugs, you too", [])
    gate.set()
    await idle(env, session.id, 1)
    with pytest.raises(PixieInTeamError):
        await env.manager.send(session.id, "@bugs, you too", [], interrupt=True)

    assert await env.manager.queued(session.id) == []
    await env.manager.send(session.id, "@qa and @scribe", [])
    await idle(env, session.id, 2)
