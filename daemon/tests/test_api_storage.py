"""Storage in Settings (B81, D104): space used, auto archive setting, large attachments and
the search index rebuild."""

import tomllib
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.paths import AppPaths
from nestd.storage.space import measure
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_search import search
from tests.test_api_sessions import create, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def upload(api: Api, name: str, data: bytes, media_type: str = "image/png") -> str:
    response = await api.http.post("/api/attachments", files={"file": (name, data, media_type)})
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/storage"),
        ("GET", "/api/storage/settings"),
        ("PUT", "/api/storage/settings"),
        ("GET", "/api/storage/attachments"),
        ("DELETE", "/api/attachments/x"),
        ("POST", "/api/search/rebuild"),
    ],
)
async def test_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_space_used_is_split_by_kind(api: Api) -> None:
    await upload(api, "a.png", b"x" * 1000)
    data = api.ctx.paths.data_dir
    (data / "artifacts" / "one").mkdir(parents=True)
    (data / "artifacts" / "one" / "page.html").write_bytes(b"y" * 300)
    (data / "logs" / "nestd.log").write_bytes(b"z" * 50)

    body = (await api.http.get("/api/storage")).json()

    assert set(body) == {
        "total_bytes",
        "chats_bytes",
        "attachments_bytes",
        "artifacts_bytes",
        "other_bytes",
    }
    assert body["attachments_bytes"] == 1000
    assert body["artifacts_bytes"] == 300
    assert body["chats_bytes"] >= (data / "nest.db").stat().st_size > 0
    assert body["other_bytes"] >= 50
    parts = ("chats_bytes", "attachments_bytes", "artifacts_bytes", "other_bytes")
    assert body["total_bytes"] == sum(body[part] for part in parts)


def test_space_without_artifacts_or_database(tmp_path: Path) -> None:
    paths = AppPaths(config_dir=tmp_path / "config", data_dir=tmp_path / "data")
    paths.data_dir.mkdir()
    (paths.data_dir / "elsewhere").symlink_to(tmp_path)  # links are not followed
    (paths.data_dir / "note").write_bytes(b"abc")

    usage = measure(paths)

    assert (usage.chats_bytes, usage.attachments_bytes, usage.artifacts_bytes) == (0, 0, 0)
    assert usage.other_bytes == 3 + (paths.data_dir / "elsewhere").lstat().st_size
    assert usage.total_bytes == usage.other_bytes


async def test_archive_setting_round_trips(api: Api) -> None:
    assert (await api.http.get("/api/storage/settings")).json() == {"archive_after_days": None}

    saved = await api.http.put("/api/storage/settings", json={"archive_after_days": 30})

    assert saved.status_code == 200
    assert saved.json() == {"archive_after_days": 30}
    assert api.ctx.settings.storage.archive_after_days == 30
    on_disk = tomllib.loads(api.ctx.paths.settings_file.read_text(encoding="utf-8"))
    assert on_disk["storage"] == {"archive_after_days": 30}
    cleared = await api.http.put("/api/storage/settings", json={"archive_after_days": None})
    assert cleared.json() == {"archive_after_days": None}


@pytest.mark.parametrize(
    "body", [{"archive_after_days": 0}, {"archive_after_days": 3651}, {"other": 1}]
)
async def test_invalid_archive_settings_are_refused(api: Api, body: dict[str, int]) -> None:
    assert (await api.http.put("/api/storage/settings", json=body)).status_code == 422


async def test_a_broken_settings_file_is_not_overwritten(api: Api) -> None:
    api.ctx.paths.settings_file.write_text("[storage\n", encoding="utf-8")

    response = await api.http.put("/api/storage/settings", json={"archive_after_days": 7})

    assert response.status_code == 409
    assert api.ctx.settings.storage.archive_after_days is None


async def test_largest_attachments_first_with_their_chat(api: Api) -> None:
    small = await upload(api, "small.png", b"s" * 10)
    big = await upload(api, "big.pdf", b"b" * 500, "application/pdf")
    api.provider.script(reply("Seen."))
    session = await create(api, prompt="Look", title="Screens", attachment_ids=[small])
    await reach(api, str(session["id"]), "idle", results=1)

    listed = (await api.http.get("/api/storage/attachments")).json()

    assert [item["id"] for item in listed] == [big, small]
    assert set(listed[0]) == {
        "id",
        "name",
        "bytes",
        "media_type",
        "session_id",
        "session_title",
        "created_at",
    }
    assert (listed[0]["name"], listed[0]["bytes"], listed[0]["media_type"]) == (
        "big.pdf",
        500,
        "application/pdf",
    )
    assert (listed[0]["session_id"], listed[0]["session_title"]) == (None, None)
    assert (listed[1]["session_id"], listed[1]["session_title"]) == (session["id"], "Screens")
    limited = (await api.http.get("/api/storage/attachments", params={"limit": 1})).json()
    assert [item["id"] for item in limited] == [big]


@pytest.mark.parametrize("limit", [0, 201])
async def test_attachment_list_limit_is_checked(api: Api, limit: int) -> None:
    response = await api.http.get("/api/storage/attachments", params={"limit": limit})

    assert response.status_code == 422


async def test_deleting_an_attachment_removes_its_file(api: Api) -> None:
    attachment = await upload(api, "a.png", b"x")
    folder = api.ctx.paths.attachments_dir / attachment

    deleted = await api.http.delete(f"/api/attachments/{attachment}")

    assert deleted.status_code == 204
    assert not folder.exists()
    assert (await api.http.get(f"/api/attachments/{attachment}")).status_code == 404
    assert (await api.http.get("/api/storage/attachments")).json() == []
    again = await api.http.delete(f"/api/attachments/{attachment}")
    assert again.status_code == 404


async def test_rebuilding_the_search_index_reindexes_everything(api: Api) -> None:
    api.provider.script(reply("The parser handles commas now."))
    session = await create(api, prompt="Fix the parser", title="Parser")
    await reach(api, str(session["id"]), "idle", results=1)
    await api.ctx.search.catch_up()
    before = await search(api, q="parser")
    await api.ctx.db.execute("DELETE FROM search_index")
    assert (await search(api, q="parser"))["hits"] == []

    response = await api.http.post("/api/search/rebuild")

    assert response.status_code == 202

    async def reindexed() -> bool:
        return (await search(api, q="parser"))["hits"] == before["hits"]

    await until(reindexed)


async def test_a_failed_rebuild_is_logged(
    api: Api, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    async def broken() -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(api.ctx.search, "catch_up", broken)

    assert (await api.http.post("/api/search/rebuild")).status_code == 202
    await until(lambda: "search rebuild failed (RuntimeError)" in caplog.text)
