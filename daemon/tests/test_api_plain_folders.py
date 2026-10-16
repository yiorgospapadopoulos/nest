"""Plain folder projects (D041): any folder works in place without git."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.events import types
from tests.api_client import Api, running_api
from tests.fake_provider import FakeRun, Turn, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git
from tests.test_api_sessions import notified, reach

NOT_GIT = {"detail": "notes is not a git repository", "code": "not_a_git_repository"}


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


def initializing(text: str) -> Turn:
    """Claude runs `git init` in the folder during the turn, then replies."""

    async def turn(run: FakeRun) -> None:
        git(run.spec.cwd, "init", "-q", "-b", "main")
        await reply(text)(run)

    return turn


async def chat(api: Api, **fields: object) -> dict[str, Any]:
    response = await api.http.post(
        "/api/sessions", json={"repo": "notes", "prompt": "Hi", **fields}
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_a_plain_folder_registers_without_git(api: Api, folder: Path) -> None:
    repo = (await api.http.get("/api/repos/notes")).json()

    assert repo["git"] is False
    assert repo["default_branch"] is None
    assert repo["path"] == str(folder)
    assert [r["git"] for r in (await api.http.get("/api/repos")).json()] == [False]
    assert not (folder / ".git").exists()


async def test_chats_in_a_plain_folder_work_in_place_without_git(api: Api, folder: Path) -> None:
    await api.http.patch("/api/repos/notes", json={"default": True})
    api.provider.script(reply("Done"), reply("Again"))

    asked = await chat(api, mode="worktree")
    defaulted = await chat(api)
    await reach(api, asked["id"], "idle", results=1)
    await reach(api, defaulted["id"], "idle", results=1)
    await notified(api, asked["id"], "finished")

    for session in (asked, defaulted):
        assert (session["mode"], session["cwd"]) == ("in_place", str(folder))
        assert (session["base_ref"], session["branch"], session["worktree_path"]) == (
            None,
            None,
            None,
        )
    assert (await api.http.get("/api/approvals")).json() == []
    stored = (await api.http.get(f"/api/sessions/{asked['id']}")).json()
    assert stored["last_error"] is None
    assert "git_violation" not in stored
    files = await api.http.get(f"/api/sessions/{asked['id']}/files", params={"q": "todo"})
    assert files.json() == {"files": ["todo.md"]}


async def test_git_actions_are_refused_for_a_plain_folder(api: Api) -> None:
    api.provider.script(reply("Done"))
    session = await chat(api)
    await reach(api, session["id"], "idle", results=1)

    responses = [
        await api.http.get(f"/api/sessions/{session['id']}/diff"),
        await api.http.post(
            f"/api/sessions/{session['id']}/approve",
            json={
                "commit_message": "x",
                "files": ["todo.md"],
                "push": False,
                "open_pr": False,
                "expected_fingerprint": "",
            },
        ),
        await api.http.get("/api/repos/notes/link-suggestions"),
    ]

    assert [(r.status_code, r.json()) for r in responses] == [(409, NOT_GIT)] * 3


async def test_a_folder_claude_initializes_becomes_a_git_project(api: Api, folder: Path) -> None:
    api.provider.script(initializing("Initialized"))
    session = await chat(api, prompt="Initialize a git repository here")
    await reach(api, session["id"], "idle", results=1)
    await notified(api, session["id"], "review_ready")

    repo = (await api.http.get("/api/repos/notes")).json()
    rows = await api.ctx.db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.REPO_UPDATED,)
    )
    review = (await api.http.get("/api/approvals")).json()
    diff = await api.http.get(f"/api/sessions/{session['id']}/diff")

    assert (repo["git"], repo["default_branch"]) == (True, "main")
    assert [(row["session_id"], json.loads(row["payload"])) for row in rows] == [
        (None, {"name": "notes", "repo": repo})
    ]
    # Everything in the new repository is up for review, as in any repo without commits.
    assert [a["payload"]["paths"] for a in review] == [["todo.md"]]
    assert diff.status_code == 200
    assert git(folder, "rev-list", "--all") == ""


async def test_the_agent_is_promised_no_review_commit_or_pull_request(api: Api) -> None:
    """BUG-46: a plain folder's work never goes up for review (D041)."""
    api.provider.script(reply("Done"))
    session = await chat(api)
    await reach(api, session["id"], "idle", results=1)

    prompt = api.provider.runs[0].spec.system_prompt_append

    assert prompt is not None
    assert prompt.startswith("You are running inside Nest")
    for promise in ("approve", "commits", "pull request"):
        assert promise not in prompt
    assert "only when the user asks" in prompt
    assert "your first action is to create every step with TaskCreate" in prompt
    assert api.provider.runs[0].spec.guard_git is False
