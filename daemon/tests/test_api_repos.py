from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.attachments.store import MAX_ATTACHMENT_BYTES
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo


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
        "default_branch": "main",
        "worktree": {"default": True, "link": [], "setup": [], "setup_timeout_seconds": 900},
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
    not_a_repo = await api.http.post("/api/repos", json={"path": str(tmp_path)})
    missing = await api.http.get("/api/repos/nope")
    missing_links = await api.http.get("/api/repos/nope/link-suggestions")
    bad_link = await api.http.put("/api/repos/project/worktree", json={"link": ["../x"]})
    missing_config = await api.http.put("/api/repos/nope/worktree", json={})

    assert duplicate.status_code == 409
    assert "already registered" in duplicate.json()["detail"]
    assert not_a_repo.status_code == 422
    assert missing.status_code == 404
    assert missing.json() == {"detail": "unknown repo 'nope'"}
    assert missing_links.status_code == 404
    assert bad_link.status_code == 422
    assert missing_config.status_code == 404


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
