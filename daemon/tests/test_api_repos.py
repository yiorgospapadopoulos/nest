import json
import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.attachments.store import MAX_ATTACHMENT_BYTES
from nestd.events import types
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
        ("GET", "/api/repos/x/branches"),
        ("PATCH", "/api/repos/x"),
        ("PUT", "/api/repos/order"),
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
    configured = await api.http.patch(
        "/api/repos/project", json={"default": False, "link": [".env"], "setup": ["make"]}
    )

    expected: dict[str, object] = {
        "name": "project",
        "path": str(repo.resolve()),
        "git": True,
        "default_branch": "main",
        # Read from git on each request (B55).
        "current_branch": "main",
        # No origin when it was registered, so a push needs the user's confirmation (D050).
        "remote_url": None,
        # No icon set: the project shows its initials in the default colour.
        "icon": None,
        "icon_color": None,
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
    bad_link = await api.http.patch("/api/repos/project", json={"link": ["../x"]})
    missing_config = await api.http.patch("/api/repos/nope", json={})
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


async def test_projects_are_reordered_and_announced(api: Api, tmp_path: Path) -> None:
    """B45: the Mac app's tab order, shared so the iPhone list follows it."""
    for name in ("alpha", "beta", "gamma"):
        await api.http.post("/api/repos", json={"path": str(init_repo(tmp_path / name))})

    reordered = await api.http.put("/api/repos/order", json={"order": ["gamma", "nope", "gamma"]})
    listed = await api.http.get("/api/repos")
    refused = await api.http.put("/api/repos/order", json={"order": ["alpha"], "extra": 1})
    missing = await api.http.put("/api/repos/order", json={})

    rows = await api.ctx.db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.REPOS_REORDERED,)
    )
    assert reordered.status_code == 200
    assert [repo["name"] for repo in reordered.json()] == ["gamma", "alpha", "beta"]
    assert reordered.json()[0]["current_branch"] == "main"
    assert listed.json() == reordered.json()
    assert [(row["session_id"], json.loads(row["payload"])) for row in rows] == [
        (None, {"order": ["gamma", "alpha", "beta"]})
    ]
    assert refused.status_code == 422
    assert missing.status_code == 422


async def updated_events(api: Api) -> list[object]:
    rows = await api.ctx.db.fetch_all(
        "SELECT session_id, payload FROM events WHERE type = ?", (types.REPO_UPDATED,)
    )
    return [(row["session_id"], json.loads(row["payload"])) for row in rows]


async def test_links_and_setup_are_edited_and_announced(api: Api, tmp_path: Path) -> None:
    """IMP-09: each client's project settings; fields left out are unchanged."""
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})
    await api.http.patch("/api/repos/project", json={"default": True, "link": [".env"]})

    setup = await api.http.patch("/api/repos/project", json={"setup": ["npm ci", "make"]})
    links = await api.http.patch("/api/repos/project", json={"link": [".env.local", "a/b.key"]})

    assert setup.status_code == 200, setup.text
    assert setup.json()["worktree"] == {
        "default": True,
        "link": [".env"],
        "setup": ["npm ci", "make"],
        "setup_timeout_seconds": 900,
    }
    assert links.json()["worktree"]["link"] == [".env.local", "a/b.key"]
    assert links.json()["worktree"]["setup"] == ["npm ci", "make"]
    assert (await api.http.get("/api/repos/project")).json() == links.json()
    # Every change reaches the other devices, the worktree default's too.
    assert await updated_events(api) == [
        (None, {"name": "project", "repo": body})
        for body in [
            {
                **links.json(),
                "worktree": {**links.json()["worktree"], "link": [".env"], "setup": []},
            },
            setup.json(),
            links.json(),
        ]
    ]


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        ({"link": ["../secrets"]}, 422, "must be a relative path inside the repository"),
        ({"link": ["/etc/passwd"]}, 422, "must be a relative path inside the repository"),
        ({"link": [""]}, 422, "must be a relative path inside the repository"),
        ({"setup": "make"}, 422, None),
        ({"link": [".git/hooks"]}, 422, "outside .git"),
        ({"default": "sometimes"}, 422, None),
        ({"other": True}, 422, None),
    ],
)
async def test_invalid_links_and_setup_are_refused(
    api: Api, tmp_path: Path, body: dict[str, object], status: int, detail: str | None
) -> None:
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})

    refused = await api.http.patch("/api/repos/project", json=body)

    assert refused.status_code == status
    if detail is not None:
        assert detail in refused.json()["detail"]
    assert (await api.http.get("/api/repos/project")).json()["worktree"]["link"] == []
    assert await updated_events(api) == []


async def test_the_worktree_default_is_set_cleared_or_left_alone(api: Api, tmp_path: Path) -> None:
    """BUG-102: an explicit null clears it (new chats follow the agent default); leaving it
    out keeps it, as null or absent links and setup do.
    """
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})

    on = await api.http.patch("/api/repos/project", json={"default": True})
    kept = await api.http.patch("/api/repos/project", json={"link": [".env"], "setup": None})
    cleared = await api.http.patch("/api/repos/project", json={"default": None})
    off = await api.http.patch("/api/repos/project", json={"default": False})

    assert [r.json()["worktree"]["default"] for r in (on, kept, cleared, off)] == [
        True,
        True,
        None,
        False,
    ]
    assert off.json()["worktree"]["link"] == [".env"]
    assert off.json()["worktree"]["setup"] == []


async def test_the_whole_worktree_config_is_no_longer_replaced(api: Api, tmp_path: Path) -> None:
    """IMP-17: both clients send only what changed, with PATCH."""
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})

    response = await api.http.put("/api/repos/project/worktree", json={"default": True})

    assert response.status_code == 405
    assert (await api.http.get("/api/repos/project")).json()["worktree"]["default"] is None


async def test_the_project_icon_is_set_cleared_or_left_alone(api: Api, tmp_path: Path) -> None:
    """B36: a pixie sprite in a pixie colour, saved in the repo's config for every device;
    an explicit null clears a key, a key left out is unchanged.
    """
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})
    config = api.ctx.paths.repos_dir / "project.toml"

    sprite = await api.http.patch("/api/repos/project", json={"icon": "frog"})
    colored = await api.http.patch("/api/repos/project", json={"icon_color": "#3DDC84"})
    saved = config.read_text(encoding="utf-8")
    worktree = await api.http.patch("/api/repos/project", json={"default": True})
    initials = await api.http.patch("/api/repos/project", json={"icon": None})
    plain = await api.http.patch("/api/repos/project", json={"icon_color": None})

    assert sprite.status_code == 200, sprite.text
    assert (sprite.json()["icon"], sprite.json()["icon_color"]) == ("frog", None)
    assert (colored.json()["icon"], colored.json()["icon_color"]) == ("frog", "#3DDC84")
    assert 'icon = "frog"' in saved
    assert 'icon_color = "#3DDC84"' in saved
    assert (worktree.json()["icon"], worktree.json()["icon_color"]) == ("frog", "#3DDC84")
    assert (initials.json()["icon"], initials.json()["icon_color"]) == (None, "#3DDC84")
    assert (plain.json()["icon"], plain.json()["icon_color"]) == (None, None)
    assert plain.json()["worktree"]["default"] is True
    assert "icon =" not in config.read_text(encoding="utf-8")
    assert "icon_color =" not in config.read_text(encoding="utf-8")
    assert (await api.http.get("/api/repos")).json() == [plain.json()]
    assert await updated_events(api) == [
        (None, {"name": "project", "repo": response.json()})
        for response in (sprite, colored, worktree, initials, plain)
    ]


@pytest.mark.parametrize(
    "body",
    [
        {"icon": "dragon"},
        {"icon": ""},
        {"icon_color": "red"},
        {"icon_color": "#12345"},
        {"icon_color": "#1234567"},
    ],
)
async def test_an_unknown_icon_or_colour_is_refused(
    api: Api, tmp_path: Path, body: dict[str, object]
) -> None:
    repo = init_repo(tmp_path / "project")
    await api.http.post("/api/repos", json={"path": str(repo)})

    refused = await api.http.patch("/api/repos/project", json=body)

    assert refused.status_code == 422
    fetched = (await api.http.get("/api/repos/project")).json()
    assert (fetched["icon"], fetched["icon_color"]) == (None, None)
    assert await updated_events(api) == []


async def test_editing_an_unknown_repo(api: Api) -> None:
    response = await api.http.patch("/api/repos/nope", json={"link": []})

    assert response.status_code == 404


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
