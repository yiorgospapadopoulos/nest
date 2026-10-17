"""Artifacts over HTTP (B79): lists, versions as JSON (never a live page), seen, delete."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

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
        "size": len(PAGE),
        "created_at": body["created_at"],
    }
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
