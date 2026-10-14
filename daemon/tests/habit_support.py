"""A daemon context with two projects for pixies' habits and reports (B42)."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from harness.context import AppContext
from harness.events import types
from harness.pixies.habit_models import CreateHabit, Habit, HabitRun
from harness.pixies.models import CreatePixie, Pixie
from harness.providers.base import AgentTool
from harness.sessions.models import Session
from tests.api_support import build_context
from tests.async_support import until
from tests.fake_provider import FakeProvider, FakeRun, Turn, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.pixie_harness_support import idle


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
    await context.habit_triggers.stop()
    await context.habit_scheduler.stop()
    await context.report_back.stop()
    await context.sessions.shutdown()
    await context.db.close()


async def make_pixie(ctx: AppContext, name: str = "Watcher", **settings: JsonValue) -> Pixie:
    return await ctx.pixies.create(CreatePixie.model_validate({"name": name, **settings}))


async def make_habit(ctx: AppContext, pixie_id: str, **fields: JsonValue) -> Habit:
    request = {"name": "Check", "prompt": "Look at CI.", **fields}
    if "schedule" not in request and "triggers" not in request:
        request["schedule"] = {"kind": "daily", "time": "09:00"}
    return await ctx.habits.create(pixie_id, CreateHabit.model_validate(request))


async def runs(ctx: AppContext, habit: Habit) -> list[HabitRun]:
    return await ctx.habits.runs(habit.pixie_id, habit.id)


async def ended(ctx: AppContext) -> None:
    """Wait until no habit run is in progress."""
    await until(lambda: ctx.habit_scheduler.current_run is None)


async def started(ctx: AppContext, provider: FakeProvider) -> None:
    """Run the due runs and wait until the one that started has its first message, as
    time passes for real between checks.
    """
    count = len(provider.runs)
    await ctx.habit_scheduler.tick()
    await until(lambda: len(provider.runs) > count and bool(provider.runs[-1].inputs))


async def run_now(ctx: AppContext, habit: Habit) -> HabitRun:
    """Run the habit now and wait until the run has ended."""
    run = await ctx.habits.run_now(habit.pixie_id, habit.id)
    await ctx.habit_scheduler.tick()
    await ended(ctx)
    return next(r for r in await runs(ctx, habit) if r.id == run.id)


def tools(run: FakeRun) -> dict[str, AgentTool]:
    return {tool.name: tool for tool in run.spec.tools}


def reporting(then: Turn | None = None, **report: JsonValue) -> Turn:
    """A habit turn that calls `report` (a warning unless told otherwise), then `then` (a
    short reply unless given).
    """

    async def turn(run: FakeRun) -> None:
        await tools(run)["report"].handler({"severity": "warn", "title": "CI is red", **report})
        await (then or reply("Reported."))(run)

    return turn


async def session_of(ctx: AppContext, run: HabitRun) -> Session:
    assert run.session_id is not None
    return await ctx.sessions.get(run.session_id)


async def published(ctx: AppContext, event_type: str) -> list[dict[str, Any]]:
    """The payloads of every stored event of the type, oldest first."""
    rows = await ctx.db.fetch_all(
        "SELECT payload FROM events WHERE type = ? ORDER BY id", (event_type,)
    )
    return [json.loads(row["payload"]) for row in rows]


async def chat_tools(
    ctx: AppContext, provider: FakeProvider, pixie: Pixie
) -> tuple[str, dict[str, AgentTool]]:
    """Open the pixie's chat with one short turn; its id and the tools its run got."""
    provider.script(reply("hi"))
    chat = await idle(ctx, (await ctx.pixies.send(pixie.id, "hello", [])).id)
    run = next(run for run in provider.runs if run.spec.cwd == chat.cwd)
    return chat.id, tools(run)


async def user_messages(ctx: AppContext, session_id: str) -> list[dict[str, Any]]:
    return [
        dict(e.payload)
        for e in await ctx.bus.session_events(session_id)
        if e.type == types.SESSION_USER_MESSAGE
    ]


async def cards(ctx: AppContext, session_id: str) -> list[dict[str, Any]]:
    return [
        dict(e.payload)
        for e in await ctx.bus.session_events(session_id)
        if e.type == types.PIXIE_CARD
    ]
