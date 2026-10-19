"""What an artifact's page remembers (B88 stage 3): one store per artifact, shared by its
versions and the user's devices, written atomically within caps, announced to open pages,
and gone with the artifact.
"""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import JsonValue

from nestd.artifacts.models import ArtifactNotFoundError, InvalidArtifactError, Origin
from nestd.artifacts.storage import (
    KEY_MAX,
    KEYS_MAX,
    STORAGE_MAX,
    VALUE_MAX,
    PageData,
    StorageQuotaError,
)
from nestd.context import AppContext
from nestd.events import types
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore

ORIGIN = Origin(session_id="s1", repo="web", chat_title="Fix the bug", pixie_id=None)


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.fixture
def events(api: Api, monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    sent: list[tuple[str, dict[str, Any]]] = []
    publish = api.ctx.bus.publish_ephemeral

    async def record(event_type: str, payload: dict[str, Any], session_id: str | None = None):  # noqa: ANN202
        sent.append((event_type, dict(payload)))
        return await publish(event_type, payload, session_id)

    monkeypatch.setattr(api.ctx.bus, "publish_ephemeral", record)
    return sent


async def page(ctx: AppContext) -> str:
    return (await ctx.artifacts.create(ORIGIN, "html", "Tracker", "<p>x</p>")).id


async def test_a_page_stores_reads_and_removes_keys(
    api: Api, events: list[tuple[str, dict[str, Any]]]
) -> None:
    artifact_id = await page(api.ctx)
    empty = await api.ctx.artifacts.storage(artifact_id)

    first = await api.ctx.artifacts.write_storage(
        artifact_id, {"habits": '["read"]', "day": "Mon"}, [], client="phone-1"
    )
    second = await api.ctx.artifacts.write_storage(artifact_id, {"day": "Tue"}, ["habits", "never"])

    assert empty == PageData(items={}, size=0)
    assert first == len("habits") + len('["read"]') + len("day") + len("Mon")
    assert second == len("day") + len("Tue")
    assert await api.ctx.artifacts.storage(artifact_id) == PageData(
        items={"day": "Tue"}, size=second
    )
    assert events == [
        (
            types.ARTIFACT_STORAGE,
            {
                "artifact_id": artifact_id,
                "set": {"habits": '["read"]', "day": "Mon"},
                "remove": [],
                "clear": False,
                "client": "phone-1",
            },
        ),
        (
            types.ARTIFACT_STORAGE,
            {
                "artifact_id": artifact_id,
                "set": {"day": "Tue"},
                "remove": ["habits", "never"],
                "clear": False,
                "client": None,
            },
        ),
    ]


async def test_storage_is_per_artifact_and_shared_by_its_versions(api: Api) -> None:
    first = await page(api.ctx)
    other = await page(api.ctx)
    await api.ctx.artifacts.write_storage(first, {"k": "v"}, [])
    await api.ctx.artifacts.update(ORIGIN, first, "<p>v2</p>", None)

    assert (await api.ctx.artifacts.storage(first)).items == {"k": "v"}
    assert (await api.ctx.artifacts.storage(other)).items == {}


async def test_sizes_count_utf8_bytes_of_keys_and_values(api: Api) -> None:
    artifact_id = await page(api.ctx)

    size = await api.ctx.artifacts.write_storage(artifact_id, {"é": "ü€"}, [])

    assert size == 2 + 2 + 3


async def test_an_empty_write_changes_nothing_and_announces_nothing(
    api: Api, events: list[tuple[str, dict[str, Any]]]
) -> None:
    artifact_id = await page(api.ctx)

    assert await api.ctx.artifacts.write_storage(artifact_id, {}, []) == 0
    assert events == []


async def test_clearing_empties_the_store_and_tells_open_pages(
    api: Api, events: list[tuple[str, dict[str, Any]]]
) -> None:
    artifact_id = await page(api.ctx)
    await api.ctx.artifacts.write_storage(artifact_id, {"a": "1", "b": "2"}, [])

    await api.ctx.artifacts.clear_storage(artifact_id, client="mac")

    assert await api.ctx.artifacts.storage(artifact_id) == PageData(items={}, size=0)
    assert events[-1] == (
        types.ARTIFACT_STORAGE,
        {"artifact_id": artifact_id, "set": {}, "remove": [], "clear": True, "client": "mac"},
    )


@pytest.mark.parametrize(
    ("write", "message"),
    [
        ({"": "x"}, f"a stored key has 1 to {KEY_MAX} characters"),
        ({"k" * (KEY_MAX + 1): "x"}, f"a stored key has 1 to {KEY_MAX} characters"),
        ({"bad\ud800": "x"}, "the key 'bad\\ud800' is not valid text"),
        ({"k": "half \ud800"}, "the value of 'k' is not valid text"),
    ],
)
async def test_bad_keys_and_values_are_refused(
    api: Api, write: dict[str, str], message: str
) -> None:
    artifact_id = await page(api.ctx)

    with pytest.raises(InvalidArtifactError) as refusal:
        await api.ctx.artifacts.write_storage(artifact_id, write, [])

    assert str(refusal.value) == message
    assert (await api.ctx.artifacts.storage(artifact_id)).items == {}


async def test_a_key_both_set_and_removed_is_refused(api: Api) -> None:
    artifact_id = await page(api.ctx)

    with pytest.raises(InvalidArtifactError, match="'k' is both set and removed"):
        await api.ctx.artifacts.write_storage(artifact_id, {"k": "v"}, ["k"])
    with pytest.raises(InvalidArtifactError, match=f"a stored key has 1 to {KEY_MAX}"):
        await api.ctx.artifacts.write_storage(artifact_id, {}, [""])


async def test_caps_are_checked_on_the_result_and_nothing_is_half_written(api: Api) -> None:
    artifact_id = await page(api.ctx)
    near = {f"k{i}": "v" for i in range(KEYS_MAX)}
    await api.ctx.artifacts.write_storage(artifact_id, near, [])

    with pytest.raises(StorageQuotaError) as too_many:
        await api.ctx.artifacts.write_storage(artifact_id, {"k0": "w", "one-more": "v"}, [])
    # Replacing a key and removing another keeps the count.
    await api.ctx.artifacts.write_storage(artifact_id, {"one-more": "v"}, ["k1"])

    data = await api.ctx.artifacts.storage(artifact_id)
    assert str(too_many.value) == (
        f"the page would store {KEYS_MAX + 1} keys; a page stores at most {KEYS_MAX}"
    )
    assert too_many.value.status_code == 413
    assert len(data.items) == KEYS_MAX
    assert data.items["k0"] == "v"
    assert "k1" not in data.items


async def test_a_value_has_at_most_256_kib(api: Api) -> None:
    artifact_id = await page(api.ctx)
    await api.ctx.artifacts.write_storage(artifact_id, {"k": "a" * VALUE_MAX}, [])

    with pytest.raises(StorageQuotaError) as refusal:
        await api.ctx.artifacts.write_storage(artifact_id, {"k": "é" * (VALUE_MAX // 2 + 1)}, [])

    assert str(refusal.value) == (
        f"the value of 'k' is {VALUE_MAX + 2} bytes; a stored value is at most {VALUE_MAX}"
        " bytes (256 KiB)"
    )


async def test_a_page_stores_at_most_2_mib(api: Api) -> None:
    artifact_id = await page(api.ctx)
    values = {f"k{i}": "a" * (VALUE_MAX - 2) for i in range(STORAGE_MAX // VALUE_MAX - 1)}
    size = await api.ctx.artifacts.write_storage(artifact_id, values, [])

    with pytest.raises(StorageQuotaError) as refusal:
        await api.ctx.artifacts.write_storage(artifact_id, {"x": "a" * (STORAGE_MAX - size)}, [])
    await api.ctx.artifacts.write_storage(artifact_id, {"x": "a" * (STORAGE_MAX - size - 1)}, [])

    assert str(refusal.value) == (
        f"the page would store {STORAGE_MAX + 1} bytes; a page stores at most {STORAGE_MAX}"
        " bytes (2 MiB)"
    )
    assert (await api.ctx.artifacts.storage(artifact_id)).size == STORAGE_MAX


async def test_storage_of_an_unknown_artifact_is_not_found(api: Api) -> None:
    for work in (
        api.ctx.artifacts.storage("nope"),
        api.ctx.artifacts.write_storage("nope", {"k": "v"}, []),
        api.ctx.artifacts.clear_storage("nope"),
    ):
        with pytest.raises(ArtifactNotFoundError):
            await work


async def test_deleting_the_artifact_deletes_its_storage(api: Api) -> None:
    artifact_id = await page(api.ctx)
    await api.ctx.artifacts.write_storage(artifact_id, {"k": "v"}, [])

    await api.ctx.artifacts.delete(artifact_id)

    rows = await api.ctx.db.fetch_all("SELECT * FROM artifact_storage")
    assert rows == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/artifacts/a/storage"),
        ("POST", "/api/artifacts/a/storage"),
        ("DELETE", "/api/artifacts/a/storage"),
    ],
)
async def test_the_storage_routes_need_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_the_storage_routes(api: Api, events: list[tuple[str, dict[str, Any]]]) -> None:
    artifact_id = await page(api.ctx)
    url = f"/api/artifacts/{artifact_id}/storage"

    written = await api.http.post(url, json={"set": {"a": "1", "b": "2"}, "client": "c1"})
    removed = await api.http.post(url, json={"remove": ["a"]})
    read = await api.http.get(url)
    cleared = await api.http.delete(url, params={"client": "c2"})
    after = await api.http.get(url)

    assert written.json() == {"size": 4}
    assert removed.json() == {"size": 2}
    assert read.json() == {"items": {"b": "2"}, "size": 2}
    assert cleared.status_code == 204
    assert after.json() == {"items": {}, "size": 0}
    assert [payload["client"] for _, payload in events] == ["c1", None, "c2"]


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        ({"set": {"k": "a" * (VALUE_MAX + 1)}}, 413, "a stored value is at most"),
        ({"set": {"": "x"}}, 422, "a stored key has 1 to"),
        ({"set": {"k": 1}}, 422, None),
        ({"remove": "k"}, 422, None),
        ({"set": {}, "client": "c" * 65}, 422, None),
    ],
)
async def test_bad_storage_writes_are_refused(
    api: Api, body: dict[str, JsonValue], status: int, detail: str | None
) -> None:
    artifact_id = await page(api.ctx)

    response = await api.http.post(f"/api/artifacts/{artifact_id}/storage", json=body)

    assert response.status_code == status
    if detail is not None:
        assert detail in response.json()["detail"]


async def test_storage_routes_of_an_unknown_artifact(api: Api) -> None:
    for method in ("GET", "POST", "DELETE"):
        response = await api.http.request(
            method, "/api/artifacts/nope/storage", json={} if method == "POST" else None
        )
        assert response.status_code == 404
