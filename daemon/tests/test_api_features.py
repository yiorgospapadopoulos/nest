"""B103: Settings > Features, what Nest can do and what is new on this device."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from nestd.features.catalog import load_catalog, packaged_catalog
from nestd.features.service import Features
from nestd.features.store import FeatureStore
from tests.api_client import Api, running_api
from tests.fakes import FakeClock, FakeSecretStore
from tests.test_api_push import pair_phone

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)

CATALOG = """
[[groups]]
id = "around"
name = "Getting around"

[[groups]]
id = "git"
name = "Worktrees and git"

[[features]]
id = "board"
group = "around"
name = "Board"
text = "Every chat as a card."
where = "Status bar"
added = 2026-10-14
block = "B39"

[[features]]
id = "branch-map"
group = "around"
name = "Branch map"
text = "Your branches as a tree."
where = "Sidebar"
added = 2026-10-21
block = "B96"

[[features]]
id = "feedback"
group = "git"
name = "Feedback back to the agent"
text = "Failed checks go to the chat with `one click`."
where = "Needs you"
added = 2026-10-14
changed = 2026-10-20
block = "B101"
"""


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    clock.current = NOW
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


@pytest.fixture
def small(api: Api, tmp_path: Path, clock: FakeClock) -> None:
    path = tmp_path / "catalog.toml"
    path.write_text(CATALOG, encoding="utf-8")
    api.ctx.features = Features(FeatureStore(api.ctx.db, clock), clock, UTC, load_catalog(path))


def new_flags(body: dict[str, Any]) -> dict[str, bool]:
    return {f["id"]: f["new"] for group in body["groups"] for f in group["features"]}


async def test_feature_routes_require_a_device_token(api: Api) -> None:
    wrong = {"Authorization": "Bearer wrong"}

    listed = await api.http.get("/api/features", headers=wrong)
    seen = await api.http.post("/api/features/seen", json={"ids": ["board"]}, headers=wrong)

    assert (listed.status_code, seen.status_code) == (401, 401)


async def test_the_shipped_catalog_is_served_in_its_order(api: Api) -> None:
    body = (await api.http.get("/api/features")).json()

    catalog = packaged_catalog()
    assert [g["id"] for g in body["groups"]] == [g.id for g in catalog.groups]
    served = [f["id"] for group in body["groups"] for f in group["features"]]
    assert sorted(served) == sorted(f.id for f in catalog.features)
    assert body["new_count"] == sum(new_flags(body).values())


@pytest.mark.usefixtures("small")
async def test_the_catalog_with_what_is_new(api: Api) -> None:
    response = await api.http.get("/api/features")

    assert response.status_code == 200
    assert response.json() == {
        "groups": [
            {
                "id": "around",
                "name": "Getting around",
                "features": [
                    {
                        "id": "board",
                        "name": "Board",
                        "text": "Every chat as a card.",
                        "where": "Status bar",
                        "added": "2026-10-14",
                        "changed": None,
                        "block": "B39",
                        "new": False,
                    },
                    {
                        "id": "branch-map",
                        "name": "Branch map",
                        "text": "Your branches as a tree.",
                        "where": "Sidebar",
                        "added": "2026-10-21",
                        "changed": None,
                        "block": "B96",
                        "new": True,
                    },
                ],
            },
            {
                "id": "git",
                "name": "Worktrees and git",
                "features": [
                    {
                        "id": "feedback",
                        "name": "Feedback back to the agent",
                        "text": "Failed checks go to the chat with `one click`.",
                        "where": "Needs you",
                        "added": "2026-10-14",
                        "changed": "2026-10-20",
                        "block": "B101",
                        "new": True,
                    },
                ],
            },
        ],
        "new_count": 2,
    }


@pytest.mark.usefixtures("small")
async def test_reading_the_list_changes_nothing(api: Api, clock: FakeClock) -> None:
    await api.http.get("/api/features")
    clock.advance(timedelta(days=3))

    body = (await api.http.get("/api/features")).json()

    # Without a recorded first visit, today moves on and the old features stop being new.
    assert body["new_count"] == 0


@pytest.mark.usefixtures("small")
async def test_shown_features_stop_being_new_at_once(api: Api, clock: FakeClock) -> None:
    seen = await api.http.post("/api/features/seen", json={"ids": ["branch-map", "unknown"]})

    assert seen.status_code == 200
    assert seen.json() == (await api.http.get("/api/features")).json()
    assert new_flags(seen.json()) == {"board": False, "branch-map": False, "feedback": True}
    assert seen.json()["new_count"] == 1

    clock.advance(timedelta(days=3))
    later = (await api.http.get("/api/features")).json()

    # The first visit stays recorded, so the feature not shown yet is still new.
    assert new_flags(later) == {"board": False, "branch-map": False, "feedback": True}


@pytest.mark.usefixtures("small")
async def test_reporting_again_keeps_the_first_showing(api: Api, clock: FakeClock) -> None:
    first = await api.http.post("/api/features/seen", json={"ids": ["branch-map"]})
    clock.advance(timedelta(hours=2))
    again = await api.http.post("/api/features/seen", json={"ids": ["branch-map"]})

    assert first.json() == again.json()
    rows = await api.ctx.db.fetch_all("SELECT feature_id, first_shown_at FROM feature_seen")
    assert [(r["feature_id"], r["first_shown_at"]) for r in rows] == [
        ("branch-map", NOW.isoformat())
    ]


@pytest.mark.usefixtures("small")
async def test_each_device_has_its_own_state(api: Api, clock: FakeClock) -> None:
    phone = await pair_phone(api)
    await api.http.post("/api/features/seen", json={"ids": ["branch-map", "feedback"]})
    clock.advance(timedelta(days=1))

    mac = (await api.http.get("/api/features")).json()
    iphone = (await api.http.get("/api/features", headers=phone)).json()

    assert mac["new_count"] == 0
    # The phone has no first visit yet: today is 2026-10-22, so only the 2026-10-21 one.
    assert new_flags(iphone) == {"board": False, "branch-map": True, "feedback": False}
    assert iphone["new_count"] == 1


@pytest.mark.parametrize("ids", [[], [f"f-{n}" for n in range(501)]])
async def test_a_report_needs_1_to_500_ids(api: Api, ids: list[str]) -> None:
    response = await api.http.post("/api/features/seen", json={"ids": ids})

    assert response.status_code == 422


async def test_a_report_of_500_ids_is_accepted(api: Api) -> None:
    response = await api.http.post(
        "/api/features/seen", json={"ids": [f"f-{n}" for n in range(500)]}
    )

    assert response.status_code == 200


async def test_a_report_without_ids_is_refused(api: Api) -> None:
    response = await api.http.post("/api/features/seen", json={"ids": "board"})

    assert response.status_code == 422
