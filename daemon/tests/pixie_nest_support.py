"""A daemon context with two projects and a pixie whose chat run has its Nest tools."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.context import AppContext
from nestd.events import types
from nestd.pixies.models import CreatePixie, Pixie
from nestd.providers.base import AgentTool, ToolRefusedError
from nestd.sessions.models import CreateSession, Session, SessionState
from tests.api_support import build_context
from tests.async_support import until
from tests.fake_provider import FakeProvider, Turn, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
async def ctx(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, provider: FakeProvider
) -> AsyncIterator[AppContext]:
    context = await build_context(tmp_path, clock, secrets, provider=provider)
    await context.repos.register(init_repo(tmp_path / "web"))
    await context.repos.register(init_repo(tmp_path / "api"))
    yield context
    await context.report_back.stop()
    await context.sessions.shutdown()
    await context.db.close()


@dataclass
class Boss:
    """A pixie with an open chat, and the tools its chat's run got."""

    ctx: AppContext
    provider: FakeProvider
    pixie: Pixie
    chat_id: str
    tools: dict[str, AgentTool]

    async def call(self, tool: str, /, **args: JsonValue) -> str:
        return await self.tools[tool].handler(args)

    async def refused(self, tool: str, /, **args: JsonValue) -> str:
        with pytest.raises(ToolRefusedError) as refusal:
            await self.tools[tool].handler(args)
        return str(refusal.value)

    async def cards(self) -> list[JsonValue]:
        events = await self.ctx.bus.session_events(self.chat_id)
        return [dict(e.payload) for e in events if e.type == types.PIXIE_CARD]


async def make_boss(ctx: AppContext, provider: FakeProvider, **settings: JsonValue) -> Boss:
    provider.script(reply("hi"))
    pixie = await ctx.pixies.create(CreatePixie.model_validate({"name": "Boss", **settings}))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await idle(ctx, chat.id)
    cwd = (await ctx.sessions.get(chat.id)).cwd
    run = next(run for run in provider.runs if run.spec.cwd == cwd)
    return Boss(ctx, provider, pixie, chat.id, {tool.name: tool for tool in run.spec.tools})


async def idle(ctx: AppContext, session_id: str) -> Session:
    async def settled() -> bool:
        session = await ctx.sessions.get(session_id)
        return session.state is SessionState.IDLE and not ctx.sessions.busy(session_id)

    await until(settled)
    return await ctx.sessions.get(session_id)


async def user_chat(
    ctx: AppContext, provider: FakeProvider, repo: str = "web", *turns: Turn
) -> Session:
    """A chat the user started, after its first turn (a short reply unless `turns`)."""
    provider.script(*(turns or (reply("done"),)))
    created = await ctx.sessions.create(
        CreateSession(repo=repo, prompt="Fix the bug", mode="worktree")
    )
    return await idle(ctx, created.id)
