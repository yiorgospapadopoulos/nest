"""A project chat's agent hears of its folder's ports and gets them in its environment
(B108).
"""

import logging
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.sessions.models import Session, SessionState
from nestd.sessions.ports import FolderPorts
from nestd.sessions.turns import NEST_PROMPT
from nestd.sessions.worktree_tool import WORKTREE_NOTE
from nestd.storage.db import Database
from tests.fake_provider import reply
from tests.fakes import FakeClock
from tests.session_support import Env

PORTS = FolderPorts(env={"NEST_PORT": "41020"}, prompt="This folder's ports are 41020 to 41029.")


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    yield environment
    await environment.manager.shutdown()


async def test_the_agent_gets_its_folders_ports_and_hears_of_them(env: Env) -> None:
    asked: list[Session] = []

    async def ports(session: Session) -> FolderPorts:
        asked.append(session)
        return PORTS

    env.manager = env.build(timedelta(hours=1), ports=ports)
    await env.register()
    env.provider.script(reply("Done."))

    created = await env.create(mode="in_place")
    await env.reach(created.id, SessionState.IDLE)

    (run,) = env.provider.runs
    assert run.spec.env == {"NEST_PORT": "41020"}
    assert run.spec.system_prompt_append == f"{NEST_PROMPT} {WORKTREE_NOTE} {PORTS.prompt}"
    assert [session.cwd for session in asked] == [env.repo_path]


async def test_without_its_ports_the_agent_runs_anyway(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    async def ports(_session: Session) -> FolderPorts:
        msg = "the database is locked"
        raise RuntimeError(msg)

    env.manager = env.build(timedelta(hours=1), ports=ports)
    await env.register()
    env.provider.script(reply("Done."))

    with caplog.at_level(logging.WARNING):
        created = await env.create(mode="in_place")
        await env.reach(created.id, SessionState.IDLE)

    (run,) = env.provider.runs
    assert run.spec.env == {}
    assert run.spec.system_prompt_append == f"{NEST_PROMPT} {WORKTREE_NOTE}"
    assert "the folder's ports of session" in caplog.text
