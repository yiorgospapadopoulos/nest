"""B115: Settings > Performance over the API."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.perf.models import Collected
from tests.api_client import Api, running_api
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.test_api_sessions import reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


async def chat(api: Api, prompt: str, answer: str) -> str:
    api.provider.script(reply(answer))
    response = await api.http.post("/api/sessions", json={"repo": "general", "prompt": prompt})
    assert response.status_code == 201, response.text
    session_id: str = response.json()["id"]
    await reach(api, session_id, "idle", results=1)
    return session_id


async def run(api: Api, *sections: str) -> dict[str, Any]:
    response = await api.http.post("/api/perf/runs", json={"sections": list(sections)})
    assert response.status_code == 200, response.text
    assert response.json()["running"]["sections"] == list(sections)
    await api.ctx.perf.settled()
    return (await api.http.get("/api/perf")).json()


def section(view: dict[str, Any], section_id: str) -> dict[str, Any]:
    return next(s for s in view["sections"] if s["id"] == section_id)


def metric(view: dict[str, Any], section_id: str, metric_id: str) -> dict[str, Any]:
    return next(m for m in section(view, section_id)["metrics"] if m["id"] == metric_id)


async def test_perf_routes_require_a_device_token(api: Api) -> None:
    wrong = {"Authorization": "Bearer wrong"}

    responses = [
        await api.http.get("/api/perf", headers=wrong),
        await api.http.post("/api/perf/runs", headers=wrong),
        await api.http.post(
            "/api/perf/client", json={"section": "mac", "metrics": {}}, headers=wrong
        ),
        await api.http.post("/api/perf/clear", headers=wrong),
    ]

    assert [r.status_code for r in responses] == [401] * 4


async def test_a_fresh_page_lists_every_section_in_order(api: Api) -> None:
    view = (await api.http.get("/api/perf")).json()

    assert [s["id"] for s in view["sections"]] == [
        "context",
        "turns",
        "load",
        "waiting",
        "activity",
        "pixies",
        "subagents",
        "reliability",
        "engines",
        "mac",
        "daemon",
        "worktrees",
        "gates",
    ]
    assert [s["advanced"] for s in view["sections"]][:5] == [False] * 5
    assert section(view, "context")["live"] is True
    assert section(view, "mac")["runner"] == "mac"
    assert (view["running"], view["last_run"], view["changes"], view["runs"]) == (None, None, [], 0)
    assert [(c["id"], c["text"]) for c in view["cards"]] == [
        ("total", "-"),
        ("cache_rate", "-"),
        ("first_reply", "-"),
        ("biggest_chat", "-"),
    ]


async def test_load_speed_measures_the_biggest_chats_through_the_routes(api: Api) -> None:
    small = await chat(api, "Hi", "Hello")
    big = await chat(api, "Write a lot", "x" * 50_000)

    view = await run(api, "load", "daemon")

    biggest = metric(view, "load", "biggest_chat")
    assert biggest["chat_id"] == big
    assert biggest["unit"] == "ms"
    assert biggest["value"] > 0
    # The chat's title and the bytes its session and transcript are.
    assert biggest["sub"].endswith("KB")
    second = metric(view, "load", "second_chat")
    assert second["chat_id"] is None
    assert second["value"] > 0
    assert small != big
    assert metric(view, "load", "open_app")["value"] > 0
    reconnect = metric(view, "load", "reconnect")
    assert reconnect["sub"].startswith("last 500 events")
    assert metric(view, "load", "slow_network")["value"] > 4 * 300
    # The run's own calls are not counted among the routes; the test's own are.
    routes = [
        m["label"] for m in section(view, "daemon")["metrics"] if m["id"].startswith("route:")
    ]
    assert "POST /api/sessions" in routes
    assert "GET /api/claude-chats" not in routes
    assert view["cards"][3]["id"] == "biggest_chat"


async def test_a_second_run_waits_for_the_first(api: Api) -> None:
    gate = asyncio.Event()

    async def slow() -> Collected:
        await gate.wait()
        return Collected()

    api.ctx.perf.collectors["gates"] = slow
    first = await api.http.post("/api/perf/runs", json={"sections": ["gates"]})
    second = await api.http.post("/api/perf/runs")

    assert first.status_code == 200
    assert second.status_code == 409
    assert (await api.http.get("/api/perf")).json()["running"]["sections"] == ["gates"]
    gate.set()
    await api.ctx.perf.settled()
    assert (await api.http.get("/api/perf")).json()["running"] is None


async def test_unknown_sections_are_refused(api: Api) -> None:
    response = await api.http.post("/api/perf/runs", json={"sections": ["mac"]})

    assert response.status_code == 422


async def test_the_mac_app_records_its_section_and_old_runs_are_cleared(api: Api) -> None:
    for layout in (900.0, 800.0, 600.0):
        response = await api.http.post(
            "/api/perf/client",
            json={"section": "mac", "metrics": {"layout_ms": layout, "memory_after": None}},
        )
        assert response.status_code == 200
    view = response.json()
    layout_metric = metric(view, "mac", "layout_ms")
    assert (layout_metric["value"], layout_metric["previous"], layout_metric["text"]) == (
        600.0,
        800.0,
        "600 ms",
    )
    assert layout_metric["change"] == {"text": "▼ 25%", "direction": "down", "tone": "better"}
    assert metric(view, "mac", "memory_after")["text"] == "-"
    assert view["runs"] == 3

    cleared = (await api.http.post("/api/perf/clear")).json()

    assert cleared["runs"] == 2
    assert metric(cleared, "mac", "layout_ms")["previous"] == 800.0
    assert (
        await api.http.post("/api/perf/client", json={"section": "load", "metrics": {}})
    ).status_code == 422
