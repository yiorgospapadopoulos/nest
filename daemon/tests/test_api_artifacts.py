"""Artifacts over HTTP (B79): lists, versions as JSON (never a live page), seen, delete."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.artifacts.bridge import SHIM_TAG, with_shim
from nestd.artifacts.models import Origin
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


PAGE = "<html><body><script>fetch('/api/sessions')</script></body></html>"


async def saved(api: Api, kind: str = "html", content: str = PAGE, title: str = "Page") -> str:
    origin = Origin(session_id="s1", repo="web", chat_title="Fix the bug", pixie_id=None)
    artifact = await api.ctx.artifacts.create(origin, kind, title, content)  # type: ignore[arg-type]
    return artifact.id


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/artifacts"),
        ("GET", "/api/artifacts/unseen"),
        ("GET", "/api/artifacts/a"),
        ("GET", "/api/artifacts/a/versions/1"),
        ("POST", "/api/artifacts/a/seen"),
        ("POST", "/api/artifacts/a/versions"),
        ("GET", "/api/artifacts/a/versions/1/files/app.js"),
        ("DELETE", "/api/artifacts/a"),
    ],
)
async def test_artifacts_need_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_list_get_read_see_and_delete(api: Api) -> None:
    page = await saved(api)
    notes = await saved(api, "markdown", "# Notes", "Notes")

    listed = await api.http.get("/api/artifacts")
    filtered = await api.http.get("/api/artifacts", params={"session_id": "s1", "repo": "api"})
    unseen = await api.http.get("/api/artifacts/unseen")
    detail = await api.http.get(f"/api/artifacts/{page}")
    content = await api.http.get(f"/api/artifacts/{page}/versions/1")
    seen = await api.http.post(f"/api/artifacts/{page}/seen")
    unseen_after = await api.http.get("/api/artifacts/unseen")
    notes_page = (await api.http.get(f"/api/artifacts/{notes}/versions/1")).json()["page"]
    deleted = await api.http.delete(f"/api/artifacts/{notes}")

    assert [a["id"] for a in listed.json()] == [notes, page]
    assert filtered.json() == []
    assert unseen.json() == {"unseen": 2}
    body = detail.json()
    assert body["chat_title"] == "Fix the bug"
    # Its chat was never stored, so it counts as deleted.
    assert body["chat_deleted"] is True
    assert [(v["version"], v["title"], v["size"]) for v in body["versions"]] == [
        (1, "Page", len(PAGE))
    ]
    # JSON, never the page itself.
    assert content.headers["content-type"] == "application/json"
    assert content.json() == {
        "artifact_id": page,
        "version": 1,
        "kind": "html",
        "title": "Page",
        "content": PAGE,
        # An HTML page is shown as saved, with the bridge's shim first.
        "page": with_shim(PAGE, {"storage": {}, "files": []}),
        "size": len(PAGE),
        "created_at": body["created_at"],
        "author": "agent",
        "files": [],
    }
    assert notes_page.startswith("<!doctype html>")
    assert SHIM_TAG in notes_page
    assert '<pre id="nest-md">\n# Notes</pre>' in notes_page
    assert seen.json()["seen"] is True
    assert unseen_after.json() == {"unseen": 1}
    assert deleted.status_code == 204
    assert [a["id"] for a in (await api.http.get("/api/artifacts")).json()] == [page]


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/api/artifacts/nope", 404),
        ("GET", "/api/artifacts/nope/versions/1", 404),
        ("POST", "/api/artifacts/nope/seen", 404),
        ("DELETE", "/api/artifacts/nope", 404),
        ("GET", "/api/artifacts/{id}/versions/2", 404),
        ("GET", "/api/artifacts/{id}/versions/0", 422),
    ],
)
async def test_unknown_artifacts_and_versions(
    api: Api, method: str, path: str, status: int
) -> None:
    artifact_id = await saved(api)

    response = await api.http.request(method, path.format(id=artifact_id))

    assert response.status_code == status


DOCUMENT = "# Plan\n\n## Goals\n\nShip it.\n"


async def test_the_user_saves_an_edited_document(api: Api) -> None:
    document = await saved(api, "document", DOCUMENT, "Plan")
    edited = DOCUMENT.replace("Ship it.", "Ship it soon.")

    response = await api.http.post(
        f"/api/artifacts/{document}/versions", json={"content": edited, "base_version": 1}
    )
    detail = (await api.http.get(f"/api/artifacts/{document}")).json()
    content = (await api.http.get(f"/api/artifacts/{document}/versions/2")).json()

    assert response.status_code == 200
    assert response.json() == {
        "version": 2,
        "title": "Plan",
        "size": len(edited),
        "created_at": detail["versions"][1]["created_at"],
        "author": "user",
    }
    assert [v["author"] for v in detail["versions"]] == ["agent", "user"]
    assert (content["content"], content["author"]) == (edited, "user")


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        ({"content": "# New", "base_version": 1}, 409, "version 1 is not the latest version (2)"),
        ({"content": " ", "base_version": 2}, 422, "an artifact needs content"),
        ({"content": "# New"}, 422, None),
        ({"content": "# New", "base_version": 0}, 422, None),
    ],
)
async def test_a_stale_or_bad_edit_is_refused(
    api: Api, body: dict[str, object], status: int, detail: str | None
) -> None:
    document = await saved(api, "document", DOCUMENT, "Plan")
    await api.ctx.artifacts.edit(document, DOCUMENT + "More.\n", 1)

    response = await api.http.post(f"/api/artifacts/{document}/versions", json=body)

    assert response.status_code == status
    if detail is not None:
        assert detail in response.json()["detail"]
    assert (await api.ctx.artifacts.detail(document)).version_count == 2


async def test_only_documents_are_edited(api: Api) -> None:
    page = await saved(api)

    response = await api.http.post(
        f"/api/artifacts/{page}/versions", json={"content": "<p>x</p>", "base_version": 1}
    )
    unknown = await api.http.post(
        "/api/artifacts/nope/versions", json={"content": "# x", "base_version": 1}
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Only documents can be edited"}
    assert unknown.status_code == 404


async def test_a_pages_files_are_listed_and_downloaded_never_shown(api: Api) -> None:
    origin = Origin(session_id="s1", repo="web", chat_title="Fix the bug", pixie_id=None)
    files: list[dict[str, JsonValue]] = [
        {"path": "app.js", "content": "start()"},
        {"path": "img/logo.svg", "content": "<svg onload=alert(1)></svg>"},
    ]
    artifact = await api.ctx.artifacts.create(
        origin, "html", "App", '<script src="app.js"></script>', files
    )
    await api.ctx.artifacts.write_storage(artifact.id, {"k": "v"}, [])
    base = f"/api/artifacts/{artifact.id}/versions/1"

    content = (await api.http.get(base)).json()
    script = await api.http.get(f"{base}/files/app.js")
    logo = await api.http.get(f"{base}/files/img/logo.svg")
    missing = await api.http.get(f"{base}/files/nope.js")
    other_version = await api.http.get(f"/api/artifacts/{artifact.id}/versions/2/files/app.js")

    assert content["files"] == [
        {"path": "app.js", "size": 7, "mime": "text/javascript"},
        {"path": "img/logo.svg", "size": 27, "mime": "image/svg+xml"},
    ]
    assert "<script>start()</script>" in content["page"]
    assert '"storage":{"k":"v"}' in content["page"]
    assert script.content == b"start()"
    assert script.headers["content-type"].startswith("text/javascript")
    assert script.headers["content-disposition"] == 'attachment; filename="app.js"'
    assert script.headers["x-content-type-options"] == "nosniff"
    assert logo.headers["content-disposition"] == 'attachment; filename="logo.svg"'
    assert (missing.status_code, other_version.status_code) == (404, 404)
