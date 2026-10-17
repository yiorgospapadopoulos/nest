from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.providers.base import ContextUsage
from nestd.sessions.extras import RunExtras
from nestd.sessions.models import Session, SessionState
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock
from tests.session_support import Env


async def fixed_extras(session: Session) -> RunExtras:
    return RunExtras(
        system_prompt=f"pixie prompt for {session.pixie_id}",
        extra_dirs=(Path("/repos/web"),),
        tools=(),
        write_root=Path("/pixies/p1/workdir"),
    )


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    environment.manager = environment.build(timedelta(hours=1), extras=fixed_extras)
    yield environment
    # Stops the chats' runs and idle timers before the loop closes.
    await environment.manager.shutdown()


def idle(env: Env, session_id: str, turns: int = 1) -> bool:
    return env.hooks.states.count((session_id, SessionState.IDLE)) >= turns


async def create(env: Env) -> Session:
    await env.db.execute(
        "INSERT INTO pixies (id, slug, name, mascot, color, permission_mode,"
        " autonomy, project_access, skills, can_call, position, created_at, updated_at)"
        " VALUES ('p1', 't', 'T', 'sprout', '#000000', 'default', 'observe', 'none',"
        " '[]', '[]', 0, 'x', 'x')"
    )
    workdir = env.paths.data_dir / "pixies" / "p1" / "workdir"
    workdir.mkdir(parents=True)
    return await env.manager.create_pixie_chat(
        pixie_id="p1",
        cwd=workdir,
        prompt="hello",
        title="Tester",
        model=None,
        effort=None,
        permission_mode="default",
        attachment_ids=[],
    )


async def test_a_pixie_chat_runs_with_its_extras_and_never_resumes(env: Env) -> None:
    env.provider.script(reply("hi", "sdk-1"), reply("again", "sdk-2"))
    session = await create(env)
    await until(lambda: len(env.provider.runs) == 1 and idle(env, session.id))

    first = env.provider.runs[0].spec
    assert session.repo == "pixie:p1"
    assert session.pixie_id == "p1"
    assert session.mode == "in_place"
    assert first.system_prompt_append == "pixie prompt for p1"
    assert Path("/repos/web") in first.extra_dirs
    assert first.write_root == Path("/pixies/p1/workdir")
    assert first.resume_id is None
    assert first.guard_git is True
    assert await env.manager.list_sessions() == []
    assert await env.manager.files(session.id, "") == []


async def test_a_full_context_opens_a_fresh_run_next_turn(env: Env) -> None:
    env.provider.context = ContextUsage(percent=61, used=122_000, limit=200_000)
    env.provider.script(reply("hi", "sdk-1"), reply("fresh", "sdk-2"))
    session = await create(env)
    await until(lambda: idle(env, session.id))

    await env.manager.send(session.id, "next", [])
    await until(lambda: len(env.provider.runs) == 2)

    assert env.provider.runs[0].closed is True
    assert env.provider.runs[1].spec.resume_id is None
    # The earlier engine session stays this session's (B31).
    assert await env.store.find_by_provider_session("sdk-1") is not None


async def test_below_the_threshold_the_run_is_kept(env: Env) -> None:
    env.provider.context = ContextUsage(percent=59, used=118_000, limit=200_000)
    env.provider.script(reply("hi", "sdk-1"), reply("same", "sdk-1"))
    session = await create(env)
    await until(lambda: idle(env, session.id))

    await env.manager.send(session.id, "next", [])
    await until(lambda: len(env.provider.runs[0].inputs) == 2)

    assert len(env.provider.runs) == 1


async def test_a_pixie_chat_without_an_extras_source_fails_loudly(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    bare = Env(tmp_path, db, clock)
    session = await create(bare)

    try:
        with pytest.raises(RuntimeError, match=f"pixie chat {session.id} has no run extras source"):
            await bare.manager._turns._pixie_extras(session)  # type: ignore[attr-defined]
    finally:
        await bare.manager.shutdown()


async def test_refreshing_a_chat_without_a_run_does_nothing(env: Env) -> None:
    env.manager.refresh_run("no-such-session")

    assert not env.manager.has_run("no-such-session")
