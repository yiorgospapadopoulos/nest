from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.sessions.models import NewSession, Session, SessionState
from nestd.sessions.store import SessionStore
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.tracking_fixture import create_task, update_task


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


class Chats:
    def __init__(self, api: Api, clock: FakeClock) -> None:
        self.api = api
        self.clock = clock
        self.store = SessionStore(api.ctx.db, clock)

    async def chat(
        self, state: SessionState, repo: str = "repo", pixie_id: str | None = None
    ) -> Session:
        """A chat updated a minute after the one before."""
        self.clock.advance(timedelta(minutes=1))
        new = NewSession(
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
        session = await self.store.create(new)
        return await self.store.update(session.id, state=state)

    async def tasks(self, session: Session, *subjects: str) -> None:
        for n, subject in enumerate(subjects, start=1):
            for part in create_task(n, subject, f"Doing {subject}"):
                await self.api.ctx.bus.publish(types.SESSION_MESSAGE, part, session.id)

    async def say(self, session: Session) -> None:
        payload: dict[str, JsonValue] = {"text": "Next", "attachments": []}
        await self.api.ctx.bus.publish(types.SESSION_USER_MESSAGE, payload, session.id)


async def test_goals_require_a_device_token(api: Api) -> None:
    response = await api.http.get("/api/goals", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_goals_list_working_chats_and_chats_with_a_visible_list(
    api: Api, clock: FakeClock
) -> None:
    chats = Chats(api, clock)
    older_list = await chats.chat(SessionState.IDLE)
    await chats.tasks(older_list, "Older")
    working = await chats.chat(SessionState.RUNNING)
    cleared = await chats.chat(SessionState.IDLE)
    await chats.tasks(cleared, "Finished")
    await chats.say(cleared)
    only_deleted = await chats.chat(SessionState.IDLE)
    await chats.tasks(only_deleted, "Dropped")
    for part in update_task("drop", "1", "deleted"):
        await api.ctx.bus.publish(types.SESSION_MESSAGE, part, only_deleted.id)
    await chats.chat(SessionState.IDLE)  # nothing to show
    archived = await chats.chat(SessionState.RUNNING)
    await chats.store.update(archived.id, archived_at=clock.now())
    pixie = (await api.http.post("/api/pixies", json={"name": "P"})).json()["id"]
    await chats.chat(SessionState.WAITING, pixie_id=pixie)  # a pixie's own chat
    other = await chats.chat(SessionState.IDLE, repo="other")
    await chats.tasks(other, "Elsewhere")
    newer_list = await chats.chat(SessionState.FAILED)
    await chats.tasks(newer_list, "Newer", "Second")
    waiting = await chats.chat(SessionState.WAITING)
    await chats.tasks(waiting, "Waiting on you")

    response = await api.http.get("/api/goals", params={"repo": "repo"})
    everywhere = await api.http.get("/api/goals")

    assert response.status_code == 200
    goals = response.json()
    assert [goal["session_id"] for goal in goals] == [
        waiting.id,
        working.id,
        newer_list.id,
        older_list.id,
    ]
    assert goals[1]["tasks"] == []
    assert [t["subject"] for t in goals[2]["tasks"]] == ["Newer", "Second"]
    assert goals[3]["tasks"] == [
        {
            "id": "1",
            "subject": "Older",
            "description": "About Older",
            "active_form": "Doing Older",
            "status": "pending",
        }
    ]
    assert [goal["session_id"] for goal in everywhere.json()] == [
        waiting.id,
        working.id,
        newer_list.id,
        other.id,
        older_list.id,
    ]


async def test_goals_of_an_unknown_repo_are_empty(api: Api) -> None:
    response = await api.http.get("/api/goals", params={"repo": "nowhere"})

    assert response.json() == []
