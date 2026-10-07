from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from harness.events import types
from tests.api_client import Api, running_api
from tests.claude_support import CHAT_A, ClaudeHome, simple_chat
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def search(api: Api, **params: str | int) -> dict[str, Any]:
    response = await api.http.get("/api/search", params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def events(api: Api, session_id: str, **params: int) -> list[int]:
    response = await api.http.get(f"/api/sessions/{session_id}/events", params=params)
    assert response.status_code == 200, response.text
    return [event["id"] for event in response.json()]


@pytest.mark.parametrize("path", ["/api/search?q=x"])
async def test_search_requires_a_device_token(api: Api, path: str) -> None:
    response = await api.http.get(path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_finds_what_the_agent_said_and_the_chat_title(api: Api) -> None:
    api.provider.script(reply("The flaky retry test is fixed."))
    session = await create(api, prompt="Make the retry test reliable", title="Retry test")
    await reach(api, str(session["id"]), "idle", results=1)
    await api.ctx.search.catch_up()

    found = await search(api, q="retry")

    assert found["indexing"] is False
    kinds = [(hit["kind"], hit["snippet"]) for hit in found["hits"]]
    assert ("title", "[[Retry]] test") in kinds
    assert ("user", "Make the [[retry]] test reliable") in kinds
    assert ("assistant", "The flaky [[retry]] test is fixed.") in kinds
    said = next(hit for hit in found["hits"] if hit["kind"] == "assistant")
    assert set(said) == {"session_id", "repo", "title", "event_id", "ts", "kind", "snippet"}
    assert (said["session_id"], said["repo"], said["title"]) == (
        session["id"],
        "repo",
        "Retry test",
    )
    message_ids = [
        e["id"]
        for e in (await api.http.get(f"/api/sessions/{session['id']}/events")).json()
        if e["type"] == types.SESSION_MESSAGE
    ]
    assert said["event_id"] == message_ids[0]
    assert (await search(api, q="retry", repo="other"))["hits"] == []
    assert len((await search(api, q="retry", limit=1))["hits"]) == 1


@pytest.mark.parametrize(
    "params", [{}, {"q": ""}, {"q": "x" * 201}, {"q": "x", "limit": 0}, {"q": "x", "limit": 101}]
)
async def test_bad_search_parameters(api: Api, params: dict[str, str | int]) -> None:
    response = await api.http.get("/api/search", params=params)

    assert response.status_code == 422


async def test_claude_code_chat_titles_are_searchable(api: Api, tmp_path: Path) -> None:
    ClaudeHome(tmp_path / "claude").write_chat(
        (tmp_path / "repo").resolve(), CHAT_A, simple_chat("Tidy the parser module")
    )
    await api.ctx.claude_chats.refresh()

    (hit,) = (await search(api, q="parser"))["hits"]

    assert (hit["session_id"], hit["kind"], hit["event_id"]) == (CHAT_A, "claude_chat", None)


async def test_events_page_before_and_after_an_event(api: Api) -> None:
    api.provider.script(reply("one"))
    session = await create(api)
    session_id = str(session["id"])
    await reach(api, session_id, "idle", results=1)
    every = await events(api, session_id)
    assert len(every) >= 6
    middle = every[3]

    assert await events(api, session_id, before=middle, limit=2) == every[1:3]
    assert await events(api, session_id, after=middle, limit=2) == every[4:6]
    assert await events(api, session_id, after=every[0], before=middle) == every[1:3]
    assert await events(api, session_id, before=middle) == every[:3]
    assert await events(api, session_id, limit=2) == every[:2]
    for bad in ({"limit": 0}, {"limit": 1001}, {"before": 0}):
        response = await api.http.get(f"/api/sessions/{session_id}/events", params=bad)
        assert response.status_code == 422
