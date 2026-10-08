import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.attachments.store import MAX_ATTACHMENT_BYTES
from harness.events import types
from tests.api_client import Api, running_api
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/repos"),
        ("POST", "/api/repos"),
        ("GET", "/api/repos/x"),
        ("GET", "/api/repos/x/link-suggestions"),
        ("PUT", "/api/repos/x/worktree"),
        ("DELETE", "/api/repos/x"),
        ("POST", "/api/attachments"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_register_list_get_and_configure_a_repo(api: Api, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "project")
    (repo / ".gitignore").write_text(".env\n", encoding="utf-8")
    (repo / ".env").write_text("A=1", encoding="utf-8")

    registered = await api.http.post("/api/repos", json={"path": str(repo)})
    listed = await api.http.get("/api/repos")
    fetched = await api.http.get("/api/repos/project")
    suggestions = await api.http.get("/api/repos/project/link-suggestions")
    configured = await api.http.put(
        "/api/repos/project/worktree", json={"default": False, "link": [".env"], "setup": ["make"]}
    )

    expected: dict[str, object] = {
        "name": "project",
        "path": str(repo.resolve()),
        "git": True,
        "default_branch": "main",
        # No origin when it was registered, so a push needs the user's confirmation (D050).
        "remote_url": None,
        # No override: new sessions follow `[agents] default_mode` (D038).
        "worktree": {"default": None, "link": [], "setup": [], "setup_timeout_seconds": 900},
    }
    assert registered.status_code == 201
    assert registered.json() == expected
    assert listed.json() == [expected]
    assert fetched.json() == expected
    assert suggestions.json() == [".env"]
    assert configured.status_code == 200
    assert configured.json()["worktree"] == {
        "default": False,
        "link": [".env"],
        "setup": ["make"],
        "setup_timeout_seconds": 900,
    }


async def test_repo_errors(api: Api, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})

    duplicate = await api.http.post("/api/repos", json={"path": str(repo), "name": "other"})
    (repo / "src").mkdir()
    not_a_root = await api.http.post("/api/repos", json={"path": str(repo / "src")})
    missing = await api.http.get("/api/repos/nope")
    missing_links = await api.http.get("/api/repos/nope/link-suggestions")
    bad_link = await api.http.put("/api/repos/project/worktree", json={"link": ["../x"]})
    missing_config = await api.http.put("/api/repos/nope/worktree", json={})
    missing_removal = await api.http.delete("/api/repos/nope")

    assert duplicate.status_code == 409
    assert "already registered" in duplicate.json()["detail"]
    assert not_a_root.status_code == 422
    assert "not the root of a git work tree" in not_a_root.json()["detail"]
    assert missing.status_code == 404
    assert missing.json() == {"detail": "unknown repo 'nope'"}
    assert missing_links.status_code == 404
    assert bad_link.status_code == 422
    assert missing_config.status_code == 404
    assert missing_removal.status_code == 404


async def test_registering_a_repo_announces_it(api: Api, tmp_path: Path) -> None:
    """BUG-32: other devices add it without reloading; the payload is that of repo.updated."""
    repo = init_repo(tmp_path / "project")

    registered = await api.http.post("/api/repos", json={"path": str(repo)})
    refused = await api.http.post("/api/repos", json={"path": str(repo)})

    rows = await api.ctx.db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.REPO_ADDED,)
    )
    assert refused.status_code == 409
    assert [(row["session_id"], json.loads(row["payload"])) for row in rows] == [
        (None, {"name": "project", "repo": registered.json()})
    ]


async def removed_events(api: Api) -> list[object]:
    rows = await api.ctx.db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.REPO_REMOVED,)
    )
    return [(row["session_id"], row["payload"]) for row in rows]


async def idle_session(api: Api, repo: str = "project") -> str:
    api.provider.script(reply("ok"))
    response = await api.http.post(
        "/api/sessions", json={"repo": repo, "prompt": "Do it", "mode": "worktree"}
    )
    session_id = str(response.json()["id"])
    await reach(api, session_id, "idle")
    return session_id


async def test_remove_a_repo_without_sessions(api: Api, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})

    removed = await api.http.delete("/api/repos/project")
    fetched = await api.http.get("/api/repos/project")
    again = await api.http.delete("/api/repos/project")

    assert removed.status_code == 204
    assert fetched.status_code == 404
    assert again.status_code == 404
    assert not (api.ctx.paths.repos_dir / "project.toml").exists()
    assert (repo / "README.md").is_file()
    assert await removed_events(api) == [(None, '{"name": "project"}')]


async def test_removing_a_repo_with_sessions_needs_purge_sessions(api: Api, tmp_path: Path) -> None:
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})
    active = await idle_session(api)
    archived = await idle_session(api)
    await api.http.patch(f"/api/sessions/{archived}", json={"archived": True})

    refused = await api.http.delete("/api/repos/project")

    assert refused.status_code == 409
    assert refused.json() == {
        "detail": "repo 'project' still has 2 session(s); "
        "delete them first or set purge_sessions=true"
    }
    assert (await api.http.get("/api/repos/project")).status_code == 200
    for session_id in (active, archived):
        assert (await api.http.get(f"/api/sessions/{session_id}")).status_code == 200
    assert await removed_events(api) == []


async def test_purge_sessions_removes_them_even_when_the_repo_folder_is_gone(
    api: Api, tmp_path: Path
) -> None:
    other = init_repo(tmp_path / "other")
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(other)})
    await api.http.post("/api/repos", json={"path": str(repo)})
    first = await idle_session(api)
    archived = await idle_session(api)
    await api.http.patch(f"/api/sessions/{archived}", json={"archived": True})
    kept = await idle_session(api, "other")
    worktrees = [
        Path((await api.http.get(f"/api/sessions/{s}")).json()["worktree_path"])
        for s in (first, archived)
    ]
    shutil.rmtree(repo)

    removed = await api.http.delete("/api/repos/project", params={"purge_sessions": True})

    assert removed.status_code == 204, removed.text
    for session_id in (first, archived):
        assert (await api.http.get(f"/api/sessions/{session_id}")).status_code == 404
    assert (await api.http.get(f"/api/sessions/{kept}")).status_code == 200
    assert not any(path.exists() for path in worktrees)
    assert [r["name"] for r in (await api.http.get("/api/repos")).json()] == ["other"]
    assert await removed_events(api) == [(None, '{"name": "project"}')]


async def test_upload_attachments(api: Api) -> None:
    response = await api.http.post(
        "/api/attachments", files={"file": ("screen shot.png", b"\x89PNG", "image/png")}
    )

    assert response.status_code == 201
    body = response.json()
    assert set(body) == {"id", "filename", "media_type", "size", "created_at"}
    assert body["filename"] == "screen_shot.png"
    assert body["media_type"] == "image/png"
    assert body["size"] == 4
    stored = api.ctx.paths.attachments_dir / body["id"] / "screen_shot.png"
    assert stored.read_bytes() == b"\x89PNG"


async def test_upload_limits_and_validation(api: Api) -> None:
    oversized = b"\0" * (MAX_ATTACHMENT_BYTES + 1)

    too_big = await api.http.post("/api/attachments", files={"file": ("a.bin", oversized)})
    missing = await api.http.post("/api/attachments", data={"other": "x"})

    assert too_big.status_code == 413
    assert missing.status_code == 422
