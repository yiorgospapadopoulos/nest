"""A pixie working for a chat shows lines in it, on every engine (B133): no turn starts,
and a pixie that stopped for the user is plain to see and heard.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import pytest

from nestd.events import types
from nestd.pixies.models import CreatePixie
from nestd.pixies.tell_chat import SHOWN, TELL_CHAT_TOOL
from nestd.providers.base import AgentTask, AgentTool, ToolRefusedError
from nestd.sessions.models import NewSession, Session
from nestd.sessions.subagents import ChatAgents
from tests.api_support import build_context
from tests.fakes import FakeClock, FakeSecretStore
from tests.test_pixie_calls import Chat, agent


@pytest.fixture
async def chat(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Chat]:
    ctx = await build_context(tmp_path, clock, secrets)
    chat = Chat(ctx, clock)
    await chat.setup()
    yield chat
    await ctx.sessions.shutdown()
    await ctx.db.close()


def tell_tool(chat: Chat, session: Session, agents: ChatAgents) -> AgentTool:
    (tool,) = [
        t for t in chat.ctx.pixie_call_runs.tools(session, agents) if t.name == TELL_CHAT_TOOL
    ]
    return tool


async def seen(chat: Chat, event_type: str) -> list[dict[str, object]]:
    events = await chat.ctx.bus.session_events(chat.session.id)
    return [dict(e.payload) for e in events if e.type == event_type]


async def working(chat: Chat) -> AgentTool:
    await chat.say(agent("a1", "scribe", background=True))
    await chat.task(AgentTask(task_id="ag1", phase="started", tool_use_id="a1", background=True))
    return tell_tool(chat, chat.session, await chat.agents())


async def test_a_line_shows_in_the_chat_and_starts_nothing(chat: Chat) -> None:
    tool = await working(chat)
    before = (await chat.ctx.sessions.get(chat.session.id)).state

    told = await tool.handler({"pixie": "scribe", "text": " Backend done,\nstarting web "})

    assert told == SHOWN
    assert await seen(chat, types.SESSION_NOTICE) == [
        {"kind": "pixie_update", "text": "@scribe: Backend done, starting web"}
    ]
    assert await seen(chat, types.NOTIFY) == []
    assert await seen(chat, types.SESSION_USER_MESSAGE) == []
    assert (await chat.ctx.sessions.get(chat.session.id)).state is before


async def test_a_waiting_pixie_is_said_and_heard(chat: Chat) -> None:
    tool = await working(chat)

    await tool.handler({"pixie": "scribe", "text": "Which database?", "waiting": True})

    assert await seen(chat, types.SESSION_NOTICE) == [
        {"kind": "pixie_waiting", "text": "@scribe: Which database?"}
    ]
    (notice,) = await seen(chat, types.NOTIFY)
    assert (notice["kind"], notice["text"]) == ("pixie_waiting", "@scribe: Which database?")


async def test_only_a_pixie_at_work_can_speak(chat: Chat) -> None:
    tool = await working(chat)

    with pytest.raises(ToolRefusedError, match="@solo has no call running"):
        await tool.handler({"pixie": "solo", "text": "Done"})

    await chat.task(AgentTask(task_id="ag1", phase="finished", status="completed"))
    with pytest.raises(ToolRefusedError, match="@scribe has no call running"):
        await tool.handler({"pixie": "scribe", "text": "Done"})
    assert await seen(chat, types.SESSION_NOTICE) == []


async def test_a_codex_chats_own_subagents_get_the_tool(chat: Chat) -> None:
    await chat.ctx.pixies.create(CreatePixie(name="Coder", provider="codex"))
    session = await chat.store.create(
        NewSession(
            repo="web",
            title="t",
            prompt="p",
            mode="in_place",
            cwd=None,
            model=None,
            effort=None,
            permission_mode="default",
            provider="codex",
        )
    )

    tool = tell_tool(chat, session, await chat.agents(session))

    assert tool.schema["required"] == ["text", "pixie"]
    assert cast("dict[str, Any]", tool.schema["properties"])["pixie"]["enum"] == ["coder"]


async def test_a_session_on_no_call_has_no_chat_to_tell(chat: Chat) -> None:
    called = await chat.new_session("web", chat.id("Solo"), chat.session.id)
    tool = tell_tool(chat, called, ChatAgents())

    with pytest.raises(ToolRefusedError, match="not on a call"):
        await tool.handler({"text": "Done"})
