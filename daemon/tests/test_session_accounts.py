"""B98: each turn starts on its engine's active account. A run opened on another account
is closed and the chat resumes on the active one; a turn already running finishes where it
began.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nestd.events import types
from nestd.providers.base import RunAccount, UsageInfo, UsageWindow
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, Turn, limits, reply
from tests.fakes import FakeClock
from tests.session_support import Env
from tests.test_session_lifecycle import until_turns

WINDOWS = UsageInfo(
    five_hour=UsageWindow(utilization=0.5, resets_at=datetime(2026, 1, 1, tzinfo=UTC)),
    seven_day=None,
)


class Accounts:
    """The engine's accounts as the session manager sees them."""

    def __init__(self) -> None:
        self.current = "claude-main"
        self.prepared: list[str] = []

    def active(self) -> str:
        return self.current

    async def prepare(self) -> RunAccount:
        self.prepared.append(self.current)
        if self.current == "claude-main":
            return RunAccount(self.current)
        return RunAccount(self.current, {"CLAUDE_CONFIG_DIR": f"/profiles/{self.current}"})


@pytest.fixture
def accounts() -> Accounts:
    return Accounts()


@pytest.fixture
async def env(
    tmp_path: Path, db: Database, clock: FakeClock, accounts: Accounts
) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.manager = environment.build(timedelta(hours=1), accounts=accounts)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


def held(gate: asyncio.Event, then: Turn) -> Turn:
    async def turn(run: FakeRun) -> None:
        await gate.wait()
        await then(run)

    return turn


async def test_a_run_opens_on_the_active_account(env: Env, accounts: Accounts) -> None:
    env.provider.script(reply("hi"))

    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    [run] = env.provider.runs
    assert run.spec.account == RunAccount("claude-main")
    assert accounts.prepared == ["claude-main"]


async def test_after_a_switch_the_next_turn_resumes_on_the_new_account(
    env: Env, accounts: Accounts
) -> None:
    env.provider.script(reply("hi"), reply("again"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    accounts.current = "0123456789ab"
    await env.manager.send(created.id, "and now?", [])
    await until_turns(env, created.id, 2)

    first, second = env.provider.runs
    assert first.closed
    assert second.spec.account == RunAccount(
        "0123456789ab", {"CLAUDE_CONFIG_DIR": "/profiles/0123456789ab"}
    )
    assert second.spec.resume_id == "sdk-1"


async def test_a_turn_running_at_the_switch_finishes_on_its_account(
    env: Env, accounts: Accounts
) -> None:
    gate = asyncio.Event()
    env.provider.script(held(gate, reply("hi")), reply("next"))
    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.RUNNING)
    # The chat is running before its run opens; a switch before then opens it on the new one.
    await until(lambda: bool(env.provider.runs and env.provider.runs[0].inputs))

    accounts.current = "0123456789ab"
    gate.set()
    await env.reach(created.id, SessionState.IDLE)
    assert len(env.provider.runs) == 1
    await env.manager.send(created.id, "next", [])
    await until_turns(env, created.id, 2)

    assert [run.spec.account.id for run in env.provider.runs if run.spec.account] == [
        "claude-main",
        "0123456789ab",
    ]


async def test_idle_runs_on_other_accounts_close_and_busy_ones_wait(
    env: Env, accounts: Accounts
) -> None:
    gate = asyncio.Event()
    env.provider.script(reply("hi"), held(gate, reply("busy")))
    idle = await env.create(mode="in_place")
    await env.reach(idle.id, SessionState.IDLE)
    busy = await env.create(mode="in_place")
    await env.reach(busy.id, SessionState.RUNNING)

    await env.manager.close_idle_runs({"claude-main"})
    await env.manager.close_idle_runs({"another"})

    idle_run, busy_run = env.provider.runs
    assert idle_run.closed
    assert not busy_run.closed
    gate.set()
    await env.reach(busy.id, SessionState.IDLE)


async def test_usage_a_run_reports_is_its_accounts_and_only_the_active_one_is_announced(
    env: Env, accounts: Accounts, db: Database
) -> None:
    gate = asyncio.Event()
    env.provider.script(limits(WINDOWS, held(gate, limits(WINDOWS, reply("hi")))))
    created = await env.create(mode="in_place")
    await until(lambda: bool(env.hooks.usage_accounts))

    accounts.current = "0123456789ab"
    gate.set()
    await env.reach(created.id, SessionState.IDLE)

    assert env.hooks.usage_accounts == ["claude-main", "claude-main"]
    rows = await db.fetch_all("SELECT payload FROM events WHERE type = ?", (types.USAGE_UPDATED,))
    assert [json.loads(row["payload"])["five_hour"]["utilization"] for row in rows] == [0.5]
