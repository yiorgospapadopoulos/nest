import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.events import types
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.claude_support import CHAT_A, CHAT_B, ClaudeHome, simple_chat, user
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


@pytest.fixture
def claude(tmp_path: Path) -> ClaudeHome:
    return ClaudeHome(tmp_path / "claude")


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return (tmp_path / "repo").resolve()


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/claude-chats"),
        ("GET", "/api/claude-chats/x"),
        ("GET", "/api/claude-chats/x/events"),
        ("POST", "/api/claude-chats/x/adopt"),
    ],
)
async def test_claude_chat_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_list_read_and_continue_a_claude_code_chat(
    api: Api, claude: ClaudeHome, root: Path
) -> None:
    claude.write_chat(root, CHAT_A, simple_chat())

    listed = (await api.http.get("/api/claude-chats", params={"repo": "repo"})).json()
    one = (await api.http.get(f"/api/claude-chats/{CHAT_A}")).json()
    events = (await api.http.get(f"/api/claude-chats/{CHAT_A}/events")).json()
    adopted = await api.http.post(f"/api/claude-chats/{CHAT_A}/adopt")
    again = await api.http.post(f"/api/claude-chats/{CHAT_A}/adopt")

    assert [chat["id"] for chat in listed] == [CHAT_A]
    assert one == listed[0]
    assert one["title"] == "Fix the login bug"
    assert one["open_in_claude_code"] is False
    assert [(e["id"], e["type"], e["session_id"]) for e in events] == [
        (1, types.SESSION_USER_MESSAGE, CHAT_A),
        (2, types.SESSION_MESSAGE, CHAT_A),
    ]
    assert adopted.status_code == 201
    session = adopted.json()
    assert (session["state"], session["mode"], session["cwd"]) == ("idle", "in_place", str(root))
    assert session["provider_session_id"] == CHAT_A
    assert again.status_code == 200
    assert again.json()["id"] == session["id"]
    assert (await api.http.get("/api/claude-chats")).json() == []
    stored = (await api.http.get(f"/api/sessions/{session['id']}/events")).json()
    assert [e["payload"] for e in stored[2:]] == [e["payload"] for e in events]

    api.provider.script(reply("Back again", provider_session_id=CHAT_A))
    sent = await api.http.post(f"/api/sessions/{session['id']}/messages", json={"text": "Go on"})
    assert sent.status_code == 202
    await until(lambda: len(api.provider.runs) == 1)
    assert api.provider.runs[0].spec.resume_id == CHAT_A


async def test_sending_while_open_in_claude_code_is_a_conflict(
    api: Api, claude: ClaudeHome, root: Path
) -> None:
    claude.write_chat(root, CHAT_A, simple_chat())
    session = (await api.http.post(f"/api/claude-chats/{CHAT_A}/adopt")).json()
    claude.open_chat(os.getpid(), CHAT_A, entrypoint="cli")

    sent = await api.http.post(f"/api/sessions/{session['id']}/messages", json={"text": "Hi"})

    assert sent.status_code == 409
    assert sent.json() == {
        "detail": "This chat is open in Claude Code right now. Close it there first.",
        "code": "open_in_claude_code",
    }
    assert api.provider.runs == []


async def test_automated_chats_are_listed_only_on_request(
    api: Api, claude: ClaudeHome, root: Path
) -> None:
    claude.write_chat(root, CHAT_A, [user("u1", "Review this change", entrypoint="sdk-py")])
    claude.write_chat(root, CHAT_B, [user("u1", "Fix the bug", entrypoint="claude-desktop")])

    default = (await api.http.get("/api/claude-chats")).json()
    every = (await api.http.get("/api/claude-chats", params={"include_automated": "true"})).json()

    assert [(c["id"], c["automated"], c["entrypoint"]) for c in default] == [
        (CHAT_B, False, "claude-desktop")
    ]
    assert sorted((c["id"], c["automated"]) for c in every) == [(CHAT_A, True), (CHAT_B, False)]


async def test_unknown_chats_and_repos(api: Api, claude: ClaudeHome, tmp_path: Path) -> None:
    claude.write_chat(tmp_path / "gone", CHAT_B, simple_chat())

    assert (await api.http.get(f"/api/claude-chats/{CHAT_B}")).status_code == 404
    assert (await api.http.get(f"/api/claude-chats/{CHAT_B}/events")).status_code == 404
    assert (await api.http.post(f"/api/claude-chats/{CHAT_B}/adopt")).status_code == 404
    assert (await api.http.get("/api/claude-chats", params={"repo": "nope"})).status_code == 404
