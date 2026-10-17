"""Chats idle for the chosen number of days are archived like a manual archive (D104)."""

import json
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.config.models import StorageSettings
from nestd.events import types
from nestd.sessions.models import UpdateSession
from nestd.storage.archiver import ChatArchiver
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def idle_chat(api: Api, title: str) -> str:
    api.provider.script(reply("Done."))
    session = await create(api, prompt="Do it", title=title, mode="in_place")
    await reach(api, str(session["id"]), "idle", results=1)
    return str(session["id"])


def keep_after(api: Api, days: int | None) -> None:
    api.ctx.settings = api.ctx.settings.model_copy(
        update={"storage": StorageSettings(archive_after_days=days)}
    )


async def archived(api: Api, session_id: str) -> bool:
    return (await api.ctx.sessions.get(session_id)).archived_at is not None


async def test_only_idle_unpinned_chats_past_the_limit_are_archived(
    api: Api, clock: FakeClock
) -> None:
    old = await idle_chat(api, "Old")
    pinned = await idle_chat(api, "Pinned")
    await api.ctx.sessions.update(pinned, UpdateSession(pinned=True))
    running = await idle_chat(api, "Running")
    await api.ctx.db.execute("UPDATE sessions SET state = 'running' WHERE id = ?", (running,))
    paused = await idle_chat(api, "Paused")
    pause = {"window": None, "resets_at": None, "resume_at": clock.now().isoformat()}
    await api.ctx.db.execute(
        "UPDATE sessions SET limit_pause = ? WHERE id = ?",
        (json.dumps({**pause, "since": clock.now().isoformat()}), paused),
    )
    clock.advance(timedelta(days=7, seconds=1))
    recent = await idle_chat(api, "Recent")
    keep_after(api, 7)

    assert await api.ctx.archiver.run_once() == [old]

    assert await archived(api, old)
    for session_id in (pinned, running, paused, recent):
        assert not await archived(api, session_id)
    events = await api.ctx.bus.session_events(old)
    updated = [e for e in events if e.type == types.SESSION_UPDATED][-1]
    changes = updated.payload["changes"]
    assert isinstance(changes, dict)
    assert "archived_at" in changes
    # Already archived: not again.
    assert await api.ctx.archiver.run_once() == []


async def test_nothing_is_archived_when_set_to_never(api: Api, clock: FakeClock) -> None:
    old = await idle_chat(api, "Old")
    clock.advance(timedelta(days=4000))

    assert await api.ctx.archiver.run_once() == []
    assert not await archived(api, old)


async def test_saving_the_setting_archives_at_once(api: Api, clock: FakeClock) -> None:
    old = await idle_chat(api, "Old")
    clock.advance(timedelta(days=31))

    saved = await api.http.put("/api/storage/settings", json={"archive_after_days": 30})

    assert saved.status_code == 200

    async def done() -> bool:
        return await archived(api, old)

    await until(done)


async def test_a_failed_check_is_logged_and_the_loop_goes_on(
    api: Api, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    calls: list[str] = []

    def settings() -> StorageSettings:
        calls.append("checked")
        if len(calls) == 1:
            raise RuntimeError("boom")
        return StorageSettings()

    archiver = ChatArchiver(
        sessions=api.ctx.sessions, clock=clock, settings=settings, interval=timedelta(hours=1)
    )
    await archiver.start()
    await until(lambda: len(calls) >= 1)
    archiver.wake()
    await until(lambda: len(calls) >= 2)
    await archiver.stop()
    await archiver.stop()

    assert "chat archive check failed (RuntimeError)" in caplog.text
