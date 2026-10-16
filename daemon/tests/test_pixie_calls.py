"""The pixies each project chat calls: recorded calls, continuing them, the group (B46)."""

from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.context import AppContext
from nestd.errors import NotFoundError
from nestd.events import types
from nestd.pixies.agents import PixieAgents
from nestd.pixies.call_models import GroupEntry, SendAway, TeamMember
from nestd.pixies.calls import CONTINUE_NOTE, PixieCallLog
from nestd.pixies.files import PixieFiles
from nestd.pixies.models import CreatePixie, CreateTeam, Pixie, UpdatePixie, WriteFile
from nestd.pixies.store import PixieStore
from nestd.pixies.team_store import TeamStore
from nestd.providers.base import AgentTask, MessageBlock, TextBlock, ToolResultBlock, ToolUseBlock
from nestd.sessions.models import NewSession, Session, SessionState
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import ChatAgents
from tests.api_support import build_context
from tests.fakes import FakeClock, FakeSecretStore


class Chat:
    """A project chat with pixies Scribe and Solo and the team @qa (Lead, Bugs)."""

    def __init__(self, ctx: AppContext, clock: FakeClock) -> None:
        self.ctx = ctx
        self.clock = clock
        self.store = SessionStore(ctx.db, clock)
        self.offered = PixieAgents(
            PixieStore(ctx.db, clock), PixieFiles(ctx.paths.pixies_dir), TeamStore(ctx.db, clock)
        )
        self.log: PixieCallLog = ctx.pixie_calls
        self.pixies: dict[str, Pixie] = {}

    async def setup(self) -> None:
        for name in ("Scribe", "Solo", "Lead", "Bugs"):
            self.pixies[name] = await self.ctx.pixies.create(CreatePixie(name=name))
        self.team = await self.ctx.teams.create(CreateTeam(name="QA", handle="qa"))
        for name in ("Lead", "Bugs"):
            await self.ctx.pixies.update(self.pixies[name].id, UpdatePixie(team_id=self.team.id))
        self.session = await self.new_session("web")

    async def new_session(self, repo: str, pixie_id: str | None = None) -> Session:
        return await self.store.create(
            NewSession(
                repo=repo,
                title="t",
                prompt="p",
                mode="in_place",
                cwd=None,
                model=None,
                effort=None,
                permission_mode="default",
                provider="fake",
                pixie_id=pixie_id,
            )
        )

    def id(self, name: str) -> str:
        return self.pixies[name].id

    async def agents(self, session: Session | None = None) -> ChatAgents:
        return await self.offered.for_session(session or self.session)

    async def say(self, *blocks: MessageBlock, session: Session | None = None) -> None:
        """The main agent's message, recorded as the session's sink would."""
        target = session or self.session
        await self.ctx.bus.publish(
            types.SESSION_MESSAGE,
            {"blocks": [b.model_dump(mode="json") for b in blocks], "parent_tool_use_id": None},
            target.id,
        )
        await self.log.message(target.id, await self.agents(target), list(blocks))

    async def sub(self, parent: str, *blocks: MessageBlock) -> None:
        """A subagent's own message: stored, never recorded."""
        await self.ctx.bus.publish(
            types.SESSION_MESSAGE,
            {"blocks": [b.model_dump(mode="json") for b in blocks], "parent_tool_use_id": parent},
            self.session.id,
        )

    async def task(self, update: AgentTask) -> None:
        await self.ctx.bus.publish(
            types.SESSION_AGENT_TASK, update.model_dump(mode="json"), self.session.id
        )
        await self.log.task(self.session.id, await self.agents(), update)

    async def note(self, text: str) -> str:
        return await self.log.note(self.session.id, await self.agents(), text)

    async def group(self) -> list[GroupEntry]:
        return await self.log.group(self.session.id)

    async def announced(self) -> list[JsonValue]:
        events = await self.ctx.bus.session_events(self.session.id)
        return [e.payload["group"] for e in events if e.type == types.SESSION_PIXIES]


def agent(call_id: str, slug: str, *, background: bool = False) -> ToolUseBlock:
    fields: dict[str, JsonValue] = {
        "subagent_type": slug,
        "prompt": f"{slug}, help",
        "description": "d",
    }
    if background:
        fields["run_in_background"] = True
    return ToolUseBlock(id=call_id, name="Agent", input=fields)


def send(call_id: str, to: JsonValue, message: str = "More") -> ToolUseBlock:
    return ToolUseBlock(id=call_id, name="SendMessage", input={"to": to, "message": message})


def handback(call_id: str, agent_id: str, report: str = "Done.") -> ToolResultBlock:
    return ToolResultBlock(
        tool_use_id=call_id,
        content=f"{report}\n\n[Subagent hand-back]\nagentId: {agent_id} (use SendMessage)",
    )


@pytest.fixture
async def chat(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Chat]:
    ctx = await build_context(tmp_path, clock, secrets)
    chat = Chat(ctx, clock)
    await chat.setup()
    yield chat
    await ctx.sessions.shutdown()
    await ctx.db.close()


async def test_a_pixie_call_is_recorded_and_ends_with_its_report(chat: Chat) -> None:
    await chat.say(TextBlock(text="Asking."), agent("a1", "scribe"))
    running = await chat.group()
    chat.clock.advance(timedelta(seconds=5))
    await chat.say(handback("a1", "ae74d5437db4d1c8d"))

    (entry,) = await chat.group()
    (call,) = entry.calls
    assert (running[0].state, running[0].calls[0].finished_at) == ("running", None)
    assert (entry.kind, entry.pixie_id, entry.team_id, entry.state) == (
        "pixie",
        chat.id("Scribe"),
        None,
        "done",
    )
    assert entry.members == []
    assert (call.tool_use_id, call.agent_id, call.continued) == ("a1", "ae74d5437db4d1c8d", False)
    assert call.finished_at is not None
    assert call.finished_at > call.started_at
    # Each change is announced with the whole group.
    assert await chat.announced() == [
        [running[0].model_dump(mode="json")],
        [entry.model_dump(mode="json")],
    ]


async def test_other_agents_and_tools_record_nothing(chat: Chat) -> None:
    await chat.say(
        agent("x1", "Explore"),
        ToolUseBlock(id="b1", name="Bash", input={"command": "ls"}),
        ToolUseBlock(id="x2", name="Agent", input={"prompt": "no type"}),
        send("s1", "unknown-agent"),
        send("s2", 7),
    )
    await chat.say(handback("x1", "abc"), ToolResultBlock(tool_use_id="b1", content="ok"))
    await chat.task(AgentTask(task_id="abc", phase="started", tool_use_id="x1"))
    await chat.task(AgentTask(task_id="abc", phase="backgrounded"))
    await chat.task(AgentTask(task_id="abc", phase="finished", status="completed"))

    assert await chat.group() == []
    assert await chat.announced() == []


async def test_a_pixie_chat_records_nothing(chat: Chat) -> None:
    own = await chat.new_session(f"pixie:{chat.id('Solo')}", pixie_id=chat.id("Solo"))

    await chat.say(agent("a1", "scribe"), session=own)
    await chat.log.task(
        own.id, await chat.agents(own), AgentTask(task_id="t", phase="finished", status="failed")
    )

    assert await chat.log.group(own.id) == []
    assert await chat.log.note(own.id, await chat.agents(own), "@scribe again") == ""


async def test_a_failed_call_fails(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    await chat.say(ToolResultBlock(tool_use_id="a1", content="boom", is_error=True))

    (entry,) = await chat.group()
    assert (entry.state, entry.calls[0].agent_id) == ("failed", None)


async def test_a_background_call_runs_until_its_task_ends(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe", background=True))
    await chat.say(
        ToolResultBlock(
            tool_use_id="a1", content="Async agent launched successfully.\nagentId: bg1 (...)"
        )
    )
    await chat.task(AgentTask(task_id="bg1", phase="started", tool_use_id="a1", background=True))
    launched = await chat.group()
    await chat.task(AgentTask(task_id="bg1", phase="finished", status="completed"))
    # The notification after the update adds the report only.
    await chat.task(
        AgentTask(
            task_id="bg1", phase="finished", tool_use_id="a1", status="completed", summary="R"
        )
    )

    (entry,) = await chat.group()
    assert (launched[0].state, launched[0].calls[0].agent_id) == ("running", "bg1")
    assert entry.state == "done"
    (work,) = await chat.log.calls(chat.session.id, chat.id("Scribe"))
    assert work.report == "R"


async def test_a_call_moved_to_the_background_ends_with_its_task(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    # A launch result without the flag still says it runs on.
    await chat.task(AgentTask(task_id="ag1", phase="started", tool_use_id="a1"))
    await chat.task(AgentTask(task_id="ag1", phase="backgrounded"))
    await chat.task(AgentTask(task_id="ag1", phase="backgrounded"))
    await chat.say(ToolResultBlock(tool_use_id="a1", content="Moved on"))
    moved = await chat.group()
    await chat.task(AgentTask(task_id="ag1", phase="finished", status="stopped"))

    (entry,) = await chat.group()
    assert (moved[0].state, moved[0].calls[0].agent_id) == ("running", "ag1")
    assert entry.state == "interrupted"


async def test_an_async_launch_result_keeps_the_call_running(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    await chat.say(ToolResultBlock(tool_use_id="a1", content="Async agent launched. agentId: z9"))
    await chat.task(AgentTask(task_id="z9", phase="finished", status="failed"))

    (entry,) = await chat.group()
    assert (entry.state, entry.calls[0].agent_id) == ("failed", "z9")


async def test_a_foreground_task_end_waits_for_the_result(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    await chat.task(AgentTask(task_id="f1", phase="started", tool_use_id="a1"))
    await chat.task(AgentTask(task_id="f1", phase="finished", status="completed", summary="S"))
    running = await chat.group()
    await chat.say(handback("a1", "f1", "The report"))

    (entry,) = await chat.group()
    assert running[0].state == "running"
    assert entry.state == "done"
    (work,) = await chat.log.calls(chat.session.id, chat.id("Scribe"))
    assert (work.report or "").startswith("The report\n")


async def test_send_message_continues_the_pixie(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    await chat.sub("a1", TextBlock(text="picked one"))
    await chat.say(handback("a1", "ag1", "ok"))
    chat.clock.advance(timedelta(seconds=5))
    await chat.say(send("s1", "ag1", "Which animal?"))
    await chat.say(
        ToolResultBlock(tool_use_id="s1", content='{"success":true,"resumedAgentId":"ag1"}')
    )
    await chat.task(AgentTask(task_id="ag1", phase="started", tool_use_id="s1", background=True))
    await chat.sub("a1", TextBlock(text="platypus"))
    resumed = await chat.group()
    await chat.task(
        AgentTask(
            task_id="ag1",
            phase="finished",
            tool_use_id="s1",
            status="completed",
            summary="platypus",
        )
    )

    (entry,) = await chat.group()
    again, first = entry.calls
    assert resumed[0].state == "running"
    assert (again.tool_use_id, again.agent_id, again.continued, again.state) == (
        "s1",
        "ag1",
        True,
        "done",
    )
    assert (first.tool_use_id, first.continued) == ("a1", False)
    later, earlier = await chat.log.calls(chat.session.id, chat.id("Scribe"))
    assert (later.prompt, later.report) == ("Which animal?", "platypus")
    assert [m.blocks for m in later.messages] == [[TextBlock(text="platypus")]]
    assert earlier.prompt == "scribe, help"
    assert (earlier.report or "").startswith("ok\n")
    assert [m.blocks for m in earlier.messages] == [[TextBlock(text="picked one")]]
    # A continued call is continued again from its first call's agent.
    await chat.say(send("s2", "ag1"))
    assert [c.continued for c in (await chat.group())[0].calls] == [True, True, False]


async def test_a_refused_send_message_fails(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    await chat.say(handback("a1", "ag1"))
    for call_id, content, error in (
        ("s1", '{"success":false,"message":"No agent"}', False),
        ("s2", "No such agent", True),
        ("s3", "not json", False),
        ("s4", "[1]", False),
    ):
        await chat.say(send(call_id, "ag1"))
        await chat.say(ToolResultBlock(tool_use_id=call_id, content=content, is_error=error))

    calls = (await chat.group())[0].calls
    assert [(c.tool_use_id, c.state) for c in calls] == [
        ("s4", "running"),
        ("s3", "running"),
        ("s2", "failed"),
        ("s1", "failed"),
        ("a1", "done"),
    ]


async def test_team_members_are_called_with_their_team(chat: Chat) -> None:
    await chat.say(agent("l1", "lead"))
    await chat.say(handback("l1", "ag-lead"))
    await chat.say(agent("s1", "solo"))
    await chat.say(agent("b1", "bugs"))

    team, solo = await chat.group()
    assert (team.kind, team.team_id, team.pixie_id, team.state) == (
        "team",
        chat.team.id,
        None,
        "running",
    )
    # The leader is the first member to join.
    assert team.members == [
        TeamMember(pixie_id=chat.id("Lead"), leader=True, state="done"),
        TeamMember(pixie_id=chat.id("Bugs"), leader=False, state="running"),
    ]
    assert [c.tool_use_id for c in team.calls] == ["b1", "l1"]
    assert (solo.kind, solo.pixie_id) == ("pixie", chat.id("Solo"))


async def test_a_team_shows_former_members_it_called_and_members_not_called_yet(
    chat: Chat,
) -> None:
    await chat.say(agent("b1", "bugs"))
    await chat.ctx.pixies.update(chat.id("Bugs"), UpdatePixie(team_id=None))

    (team,) = await chat.group()

    assert team.members == [
        TeamMember(pixie_id=chat.id("Lead"), leader=True, state=None),
        TeamMember(pixie_id=chat.id("Bugs"), leader=False, state="running"),
    ]


async def test_a_deleted_team_leaves_its_calls_solo(chat: Chat) -> None:
    await chat.say(agent("b1", "bugs"))
    await chat.ctx.teams.delete(chat.team.id)

    (entry,) = await chat.group()

    assert (entry.kind, entry.pixie_id) == ("pixie", chat.id("Bugs"))


async def test_a_pixie_tagged_again_is_told_to_continue(chat: Chat) -> None:
    assert await chat.note("@scribe hello") == ""
    await chat.say(agent("a1", "scribe"))
    assert await chat.note("@scribe hello") == ""
    await chat.say(handback("a1", "ag1"))
    await chat.say(agent("a2", "solo"))
    await chat.say(handback("a2", "ag2"))

    assert await chat.note("@scribe and @solo, again") == (
        CONTINUE_NOTE.format(slug="scribe", agent_id="ag1")
        + CONTINUE_NOTE.format(slug="solo", agent_id="ag2")
    )
    assert CONTINUE_NOTE.format(slug="scribe", agent_id="ag1") == (
        "\n\n(@scribe was called earlier in this chat as agent ag1. Continue that agent with"
        " SendMessage to 'ag1' instead of starting a new one.)"
    )
    assert await chat.note("no mention of scribe") == ""


async def test_a_changed_pixie_starts_fresh(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    await chat.say(handback("a1", "ag1"))
    soul = await chat.ctx.pixies.read_file(chat.id("Scribe"), "soul")
    await chat.ctx.pixies.write_file(
        chat.id("Scribe"), "soul", WriteFile(text="A new soul.", hash=soul.hash)
    )

    assert await chat.note("@scribe again") == ""
    # Its fresh call is the one continued from then on.
    await chat.say(agent("a2", "scribe"))
    await chat.say(handback("a2", "ag2"))
    assert await chat.note("@scribe again") == CONTINUE_NOTE.format(slug="scribe", agent_id="ag2")


async def test_a_team_call_continues_its_members(chat: Chat) -> None:
    await chat.say(agent("l1", "lead"))
    await chat.say(handback("l1", "ag-lead"))

    assert await chat.note("@qa again") == CONTINUE_NOTE.format(slug="lead", agent_id="ag-lead")


async def test_send_away_leaves_the_group_and_forgets_the_agent(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"))
    await chat.say(handback("a1", "ag1"))
    await chat.say(agent("a2", "solo"))
    before = len(await chat.announced())

    left = await chat.log.send_away(chat.session.id, SendAway(pixie_id=chat.id("Scribe")))
    again = await chat.log.send_away(chat.session.id, SendAway(pixie_id=chat.id("Scribe")))

    assert [e.pixie_id for e in left] == [chat.id("Solo")]
    assert again == left
    # Announced once: the second changed nothing.
    assert len(await chat.announced()) == before + 1
    assert await chat.note("@scribe hi") == ""
    assert await chat.log.calls(chat.session.id, chat.id("Scribe")) == []
    # Calling it again brings it back, fresh.
    await chat.say(agent("a3", "scribe"))
    assert [c.tool_use_id for c in (await chat.group())[-1].calls] == ["a3"]


async def test_send_away_a_team_takes_its_members(chat: Chat) -> None:
    await chat.say(agent("l1", "lead"))
    await chat.say(handback("l1", "ag-lead"))
    await chat.say(agent("s1", "solo"))

    left = await chat.log.send_away(chat.session.id, SendAway(team_id=chat.team.id))

    assert [e.pixie_id for e in left] == [chat.id("Solo")]
    assert await chat.note("@qa again") == ""


def test_send_away_names_one_pixie_or_team() -> None:
    for fields in ({}, {"pixie_id": "p", "team_id": "t"}):
        with pytest.raises(ValueError, match="either a pixie_id or a team_id"):
            SendAway.model_validate(fields)


async def test_a_cut_off_turn_interrupts_its_calls(chat: Chat) -> None:
    await chat.say(agent("a1", "scribe"), agent("a2", "solo", background=True))
    session = await chat.store.update(chat.session.id, state=SessionState.IDLE)
    await chat.log.state_changed(session)
    unchanged = len(await chat.announced())
    for state in (SessionState.FAILED, SessionState.INTERRUPTED):
        await chat.log.state_changed(await chat.store.update(chat.session.id, state=state))

    scribe, solo = await chat.group()
    # Background work outlives the turn, until the chat closes.
    assert (scribe.state, solo.state) == ("interrupted", "running")
    assert len(await chat.announced()) == unchanged + 1
    await chat.log.state_changed(
        await chat.store.update(chat.session.id, state=SessionState.CLOSED)
    )
    assert (await chat.group())[1].state == "interrupted"
    await chat.log.purged(chat.session.id)


async def test_calls_left_running_by_a_previous_process_are_interrupted(chat: Chat) -> None:
    other = await chat.new_session("web")
    await chat.say(agent("a1", "scribe"))
    await chat.say(agent("a2", "solo"), session=other)
    await chat.say(agent("a3", "bugs"))
    await chat.say(handback("a3", "ag3"))

    await chat.log.stop_stale()

    states = {c.tool_use_id: c.state for e in await chat.group() for c in e.calls}
    assert states == {"a1": "interrupted", "a3": "done"}
    assert (await chat.log.group(other.id))[0].state == "interrupted"
    assert (await chat.announced())[-1] == [e.model_dump(mode="json") for e in await chat.group()]


async def test_an_ordinary_subagents_transcript(chat: Chat) -> None:
    await chat.say(agent("x1", "Explore"))
    await chat.sub("x1", TextBlock(text="looking"))

    work = await chat.log.agent_transcript(chat.session.id, "x1")

    assert (work.prompt, [m.blocks for m in work.messages], work.report) == (
        "Explore, help",
        [[TextBlock(text="looking")]],
        None,
    )
    with pytest.raises(NotFoundError, match="no agent call 'nope'"):
        await chat.log.agent_transcript(chat.session.id, "nope")


async def test_a_call_whose_messages_are_gone_keeps_its_state(chat: Chat) -> None:
    # Recorded, but its events were cut away since, as a rewind of the conversation does.
    await chat.log.message(chat.session.id, await chat.agents(), [agent("a1", "scribe")])
    await chat.task(AgentTask(task_id="t1", phase="started"))

    (work,) = await chat.log.calls(chat.session.id, chat.id("Scribe"))

    assert (work.tool_use_id, work.state, work.agent_id) == ("a1", "running", None)
    assert (work.prompt, work.messages, work.report) == (None, [], None)
