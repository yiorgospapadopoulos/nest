"""B59: the composer's `!` commands and `#` memory through the API."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    path = tmp_path / "notes"
    path.mkdir()
    (path / "todo.md").write_text("- write\n", encoding="utf-8")
    return path.resolve()


@pytest.fixture
async def api(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, folder: Path
) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        response = await running.http.post("/api/repos", json={"path": str(folder)})
        assert response.status_code == 201, response.text
        yield running


async def chat(api: Api) -> str:
    response = await api.http.post("/api/sessions", json={"repo": "notes", "prompt": "Hi"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_a_command_runs_in_the_chats_folder(api: Api, folder: Path) -> None:
    session_id = await chat(api)

    response = await api.http.post(f"/api/sessions/{session_id}/shell", json={"command": " ls "})

    assert response.status_code == 200
    assert response.json() == {
        "command": "ls",
        "exit_code": 0,
        "output": "todo.md\n",
        "truncated": False,
        "timed_out": False,
        "context": (
            "<bash-input>ls</bash-input>\n"
            "<bash-stdout>todo.md</bash-stdout><bash-stderr></bash-stderr>"
        ),
    }


async def test_a_pixie_chat_cannot_run_commands(api: Api) -> None:
    pixie = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]
    pixie_chat = (await api.http.post(f"/api/pixies/{pixie}/messages", json={"text": "go"})).json()

    response = await api.http.post(
        f"/api/sessions/{pixie_chat['id']}/shell", json={"command": "ls"}
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "A pixie's chat cannot run shell commands.",
        "code": "pixie_chat",
    }


async def test_invalid_requests_are_refused(api: Api) -> None:
    session_id = await chat(api)

    empty = await api.http.post(f"/api/sessions/{session_id}/shell", json={"command": "  "})
    scope = await api.http.post(
        f"/api/sessions/{session_id}/memory", json={"text": "x", "scope": "team"}
    )
    unknown = await api.http.post("/api/sessions/nope/shell", json={"command": "ls"})
    del api.http.headers["Authorization"]
    anonymous = await api.http.post(f"/api/sessions/{session_id}/shell", json={"command": "ls"})

    assert empty.status_code == 422
    assert scope.status_code == 422
    assert unknown.status_code == 404
    assert anonymous.status_code == 401


async def test_memory_goes_to_the_projects_or_the_users_claude_md(
    api: Api, folder: Path, tmp_path: Path
) -> None:
    session_id = await chat(api)

    project = await api.http.post(
        f"/api/sessions/{session_id}/memory",
        json={"text": "Notes are in todo.md", "scope": "project"},
    )
    user = await api.http.post(
        f"/api/sessions/{session_id}/memory", json={"text": "Answer briefly", "scope": "user"}
    )

    assert project.status_code == 200
    assert project.json() == {
        "path": str(folder / "CLAUDE.md"),
        "scope": "project",
        "line": "- Notes are in todo.md",
    }
    assert (folder / "CLAUDE.md").read_text(encoding="utf-8") == "- Notes are in todo.md\n"
    assert user.json()["path"] == str(tmp_path / "claude" / "CLAUDE.md")
    assert (tmp_path / "claude" / "CLAUDE.md").read_text(encoding="utf-8") == "- Answer briefly\n"
