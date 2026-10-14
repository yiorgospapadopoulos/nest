"""Habits, runs and reports over HTTP (B42), with the daemon's scheduler running."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.pixies.reporting import FromRun
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.pixie_harness_support import idle


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        yield running


HABIT = {
    "name": "Morning check",
    "prompt": "Check CI on main.",
    "schedule": {"kind": "daily", "time": "09:00"},
}


async def pixie(api: Api, name: str = "Watcher") -> str:
    return (await api.http.post("/api/pixies", json={"name": name})).json()["id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/pixies/p/habits"),
        ("POST", "/api/pixies/p/habits/h/run"),
        ("GET", "/api/pixie-reports"),
        ("POST", "/api/pixie-reports/r/read"),
        ("POST", "/api/pixies/p/reports/read"),
    ],
)
async def test_habits_and_reports_need_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_habit_crud(api: Api) -> None:
    pid = await pixie(api)
    created = await api.http.post(f"/api/pixies/{pid}/habits", json=HABIT)
    hid = created.json()["id"]
    no_start = await api.http.post(f"/api/pixies/{pid}/habits", json={"name": "N", "prompt": "P"})
    bad_time = await api.http.post(
        f"/api/pixies/{pid}/habits",
        json={"name": "N", "prompt": "P", "schedule": {"kind": "daily", "time": "9am"}},
    )
    patched = await api.http.patch(
        f"/api/pixies/{pid}/habits/{hid}",
        json={"triggers": ["failed"], "schedule": None, "enabled": False},
    )
    emptied = await api.http.patch(f"/api/pixies/{pid}/habits/{hid}", json={"triggers": []})
    listed = await api.http.get(f"/api/pixies/{pid}/habits")
    unknown_pixie = await api.http.get("/api/pixies/nope/habits")
    unknown_habit = await api.http.patch(f"/api/pixies/{pid}/habits/nope", json={"name": "X"})
    deleted = await api.http.delete(f"/api/pixies/{pid}/habits/{hid}")
    after = await api.http.get(f"/api/pixies/{pid}/habits")

    assert created.status_code == 201
    assert set(created.json()) == {
        "id",
        "pixie_id",
        "name",
        "prompt",
        "schedule",
        "triggers",
        "max_minutes",
        "enabled",
        "created_at",
        "updated_at",
        "next_due_at",
        "last_run",
    }
    assert created.json()["max_minutes"] == 20
    assert created.json()["next_due_at"] == "2026-01-02T09:00:00Z"
    assert (no_start.status_code, bad_time.status_code) == (422, 422)
    assert patched.json()["schedule"] is None
    assert (patched.json()["triggers"], patched.json()["enabled"]) == (["failed"], False)
    assert emptied.status_code == 422
    assert emptied.json() == {"detail": "a habit needs a schedule or at least one trigger"}
    assert [h["id"] for h in listed.json()] == [hid]
    assert (unknown_pixie.status_code, unknown_habit.status_code) == (404, 404)
    assert deleted.status_code == 204
    assert after.json() == []


async def test_run_now_and_the_history(api: Api) -> None:
    pid = await pixie(api)
    hid = (await api.http.post(f"/api/pixies/{pid}/habits", json=HABIT)).json()["id"]
    api.provider.script(reply("Nothing to report."))

    queued = await api.http.post(f"/api/pixies/{pid}/habits/{hid}/run")

    async def done() -> bool:
        history = (await api.http.get(f"/api/pixies/{pid}/habits/{hid}/runs")).json()
        return [r["outcome"] for r in history] == ["quiet"]

    await until(done)
    [run] = (await api.http.get(f"/api/pixies/{pid}/habits/{hid}/runs")).json()
    transcript = await api.http.get(f"/api/sessions/{run['session_id']}/events")
    sessions = await api.http.get("/api/sessions")
    habit = (await api.http.get(f"/api/pixies/{pid}/habits")).json()[0]

    assert queued.status_code == 202
    assert queued.json()["outcome"] == "queued"
    assert set(queued.json()) == {
        "id",
        "habit_id",
        "pixie_id",
        "session_id",
        "due_at",
        "started_at",
        "ended_at",
        "outcome",
        "reason",
        "report_title",
    }
    assert run["id"] == queued.json()["id"]
    assert transcript.status_code == 200
    assert sessions.json() == []
    assert habit["last_run"]["outcome"] == "quiet"
    unknown = await api.http.post(f"/api/pixies/{pid}/habits/nope/run")
    assert unknown.status_code == 404


async def test_reports_their_reading_and_the_pixies_settings(api: Api) -> None:
    pid = await pixie(api)
    api.provider.script(reply("hi"))
    chat = (await api.http.post(f"/api/pixies/{pid}/messages", json={"text": "hi"})).json()
    await idle(api.ctx, chat["id"])
    hid = (await api.http.post(f"/api/pixies/{pid}/habits", json=HABIT)).json()["id"]
    run = await api.ctx.habit_scheduler._store.add_run(  # pyright: ignore[reportPrivateUsage]
        await api.ctx.habit_scheduler._store.get(hid),  # pyright: ignore[reportPrivateUsage]
        "manual",
        api.ctx.clock.now(),
    )
    # Ended already, so the running scheduler leaves it alone.
    await api.ctx.habit_scheduler._store.update_run(run.id, outcome="quiet")  # pyright: ignore[reportPrivateUsage]
    await api.ctx.reports.report(pid, "warn", "Lint is red", "", None, chat["id"])
    api.provider.script(reply("I see."))
    action = await api.ctx.reports.report(
        pid, "action", "Merge waits", "", None, FromRun(run.id, hid, "Morning check")
    )
    pushed = await api.http.patch(f"/api/pixies/{pid}", json={"report_push": "warn"})
    bad_push = await api.http.patch(f"/api/pixies/{pid}", json={"report_push": "loud"})

    everything = await api.http.get("/api/pixie-reports")
    unread = await api.http.get("/api/pixie-reports", params={"unread": "true"})
    read = await api.http.post(f"/api/pixie-reports/{action.id}/read")
    unknown = await api.http.post("/api/pixie-reports/nope/read")
    still_unread = await api.http.get("/api/pixie-reports", params={"unread": "true"})
    all_read = await api.http.post(f"/api/pixies/{pid}/reports/read")
    unknown_pixie = await api.http.post("/api/pixies/nope/reports/read")
    after = (await api.http.get(f"/api/pixies/{pid}")).json()
    kinds = (await api.http.get("/api/notifications/settings")).json()["kinds"]

    assert pushed.json()["report_push"] == "warn"
    assert pushed.json()["unread_action_reports"] == 1
    assert bad_push.status_code == 422
    assert [r["title"] for r in everything.json()] == ["Merge waits", "Lint is red"]
    assert everything.json()[0]["habit_name"] == "Morning check"
    assert set(everything.json()[0]) == {
        "id",
        "pixie_id",
        "severity",
        "title",
        "body",
        "link",
        "habit_id",
        "habit_name",
        "run_id",
        "created_at",
        "read_at",
    }
    assert len(unread.json()) == 2
    assert read.json()["read_at"] is not None
    assert unknown.status_code == 404
    assert [r["title"] for r in still_unread.json()] == ["Lint is red"]
    assert all_read.json() == {"ids": [still_unread.json()[0]["id"]]}
    assert unknown_pixie.status_code == 404
    assert (after["report_push"], after["unread_action_reports"]) == ("warn", 0)
    assert kinds["pixie_report"] is True
