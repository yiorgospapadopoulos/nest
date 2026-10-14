"""Plan approvals, the context meter, command reports and file suggestions (D032)."""

import logging
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.approvals.models import ApprovalKind, ApprovalStatus
from nestd.events import types
from nestd.providers.base import (
    AccountInfo,
    CommandCatalog,
    ContextUsage,
    EngineDetails,
    PlanDecision,
    SlashCommand,
)
from nestd.sessions.errors import NoWorkspaceError
from nestd.sessions.models import SessionState
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import catalog, engine, plan, reply
from tests.fakes import FakeClock
from tests.session_support import Env
from tests.test_session_store import new_session


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def test_an_approved_plan_switches_the_session_to_accept_edits(env: Env) -> None:
    env.provider.script(plan("# Plan\n1. Add tests", reply("building")))
    created = await env.create(permission_mode="plan")
    await env.reach(created.id, SessionState.WAITING)
    (item,) = await env.approvals.list_approvals(ApprovalStatus.PENDING)

    await env.approvals.resolve(item.id, {"decision": "approve"})
    session = await env.reach(created.id, SessionState.IDLE)

    assert item.kind is ApprovalKind.PLAN
    assert item.payload == {"plan": "# Plan\n1. Add tests", "tool_use_id": "toolu_plan"}
    assert env.provider.runs[0].plans == [PlanDecision(approved=True, mode="acceptEdits")]
    assert session.permission_mode == "acceptEdits"
    updates = [
        e.payload["changes"]
        for e in await env.bus.session_events(created.id)
        if e.type == types.SESSION_UPDATED
    ]
    assert updates == [{"permission_mode": "acceptEdits"}]
    # The engine switched itself through the approval; no separate mode change is sent.
    assert env.provider.runs[0].calls == []


async def test_approving_a_plan_in_accept_edits_changes_nothing(env: Env) -> None:
    env.provider.script(plan("plan", reply("ok")))
    created = await env.create(permission_mode="acceptEdits")
    await env.reach(created.id, SessionState.WAITING)
    (item,) = await env.approvals.list_approvals(ApprovalStatus.PENDING)

    await env.approvals.resolve(item.id, {"decision": "approve"})
    await env.reach(created.id, SessionState.IDLE)

    assert types.SESSION_UPDATED not in await env.event_types(created.id)


async def test_interrupting_expires_a_pending_plan(env: Env) -> None:
    env.provider.script(plan("plan", reply("stopped")))
    created = await env.create(permission_mode="plan")
    await env.reach(created.id, SessionState.WAITING)

    await env.manager.interrupt(created.id)
    await until(lambda: bool(env.provider.runs[0].plans))

    assert env.provider.runs[0].plans == [
        PlanDecision(approved=False, message="interrupted by the user")
    ]


async def test_context_usage_is_kept_and_announced_after_each_turn(env: Env) -> None:
    env.provider.context = ContextUsage(percent=41.2, used=82400, limit=200000)
    env.provider.script(reply("done"))
    created = await env.create()

    session = await env.reach(created.id, SessionState.IDLE)

    assert session.context == ContextUsage(percent=41.2, used=82400, limit=200000)
    contexts = [
        e.payload
        for e in await env.bus.session_events(created.id)
        if e.type == types.SESSION_CONTEXT
    ]
    assert contexts == [{"context": {"percent": 41.2, "used": 82400, "limit": 200000}}]
    events = await env.event_types(created.id)
    assert events.index(types.SESSION_CONTEXT) < len(events) - 1 - events[::-1].index(
        types.SESSION_STATE
    )


async def test_context_usage_failures_leave_the_meter_alone(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    env.provider.context_error = RuntimeError("control request timed out")
    env.provider.script(reply("done"))
    created = await env.create()

    with caplog.at_level(logging.WARNING):
        session = await env.reach(created.id, SessionState.IDLE)

    assert session.context is None
    assert (
        f"the context report of session {created.id} failed"
        " (RuntimeError: control request timed out)"
    ) in caplog.text
    assert types.SESSION_CONTEXT not in await env.event_types(created.id)


async def test_without_context_usage_nothing_is_announced(env: Env) -> None:
    env.provider.script(reply("done"))
    created = await env.create()

    session = await env.reach(created.id, SessionState.IDLE)

    assert session.context is None
    assert types.SESSION_CONTEXT not in await env.event_types(created.id)


async def test_reported_commands_reach_the_hooks(env: Env) -> None:
    reported = CommandCatalog(commands=[SlashCommand(name="compact")])
    env.provider.script(catalog(reported, reply("ok")))
    created = await env.create()

    await env.reach(created.id, SessionState.IDLE)

    assert env.hooks.commands == [(created.id, reported)]


async def test_reported_engine_details_reach_the_hooks(env: Env) -> None:
    reported = EngineDetails(account=AccountInfo(plan="Claude Max"))
    env.provider.script(engine(reported, reply("ok")))
    created = await env.create()

    await env.reach(created.id, SessionState.IDLE)

    assert env.hooks.engine == [reported]


async def test_file_suggestions_come_from_the_working_directory(env: Env) -> None:
    env.provider.script(reply("ok"))
    created = await env.create(mode="in_place")
    session = await env.reach(created.id, SessionState.IDLE)
    assert session.cwd is not None
    (session.cwd / "notes.md").write_text("new", encoding="utf-8")

    files = await env.manager.files(created.id, "notes")

    assert files == ["notes.md"]


async def test_file_suggestions_need_the_working_directory(env: Env, tmp_path: Path) -> None:
    session = await env.store.create(new_session(cwd=tmp_path / "gone"))

    with pytest.raises(NoWorkspaceError):
        await env.manager.files(session.id, "")
