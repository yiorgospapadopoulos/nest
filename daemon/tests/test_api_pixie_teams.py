from collections.abc import AsyncIterator
from pathlib import Path

import pytest

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
        ("GET", "/api/pixie-teams"),
        ("POST", "/api/pixie-teams"),
        ("PATCH", "/api/pixie-teams/x"),
        ("DELETE", "/api/pixie-teams/x"),
        ("POST", "/api/pixies/x/duplicate"),
    ],
)
async def test_teams_need_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_teams_crud_and_leaders(api: Api) -> None:
    created = await api.http.post("/api/pixie-teams", json={"name": "QA"})
    tid = created.json()["id"]
    a = (await api.http.post("/api/pixies", json={"name": "A"})).json()["id"]
    b = (await api.http.post("/api/pixies", json={"name": "B"})).json()["id"]
    outsider = (await api.http.post("/api/pixies", json={"name": "O"})).json()["id"]

    joined = await api.http.patch(f"/api/pixies/{a}", json={"team_id": tid})
    await api.http.patch(f"/api/pixies/{b}", json={"team_id": tid})
    led = await api.http.patch(f"/api/pixie-teams/{tid}", json={"leader_id": b, "name": "Q"})
    refused = await api.http.patch(f"/api/pixie-teams/{tid}", json={"leader_id": outsider})
    unknown_team = await api.http.patch(f"/api/pixies/{a}", json={"team_id": "nope"})
    taken = await api.http.post("/api/pixie-teams", json={"name": "X", "handle": "a"})
    bad = await api.http.post("/api/pixie-teams", json={"name": "X", "handle": "plan"})
    left = await api.http.patch(f"/api/pixies/{a}", json={"team_id": None})
    listed = await api.http.get("/api/pixie-teams")
    deleted = await api.http.delete(f"/api/pixie-teams/{tid}")
    gone = await api.http.delete(f"/api/pixie-teams/{tid}")
    pixies = await api.http.get("/api/pixies")

    assert created.status_code == 201
    assert created.json() | {"id": "", "created_at": "", "updated_at": ""} == {
        "id": "",
        "name": "QA",
        "handle": "qa",
        "leader_id": None,
        "position": 0,
        "created_at": "",
        "updated_at": "",
    }
    assert joined.json()["team_id"] == tid
    assert (led.json()["leader_id"], led.json()["name"]) == (b, "Q")
    assert refused.status_code == 409
    assert refused.json() == {
        "detail": "the leader must be one of the team's pixies",
        "code": "leader_not_member",
    }
    assert unknown_team.status_code == 404
    assert taken.status_code == 409
    assert bad.status_code == 422
    assert left.json()["team_id"] is None
    assert [t["id"] for t in listed.json()] == [tid]
    assert deleted.status_code == 204
    assert gone.status_code == 404
    assert [p["team_id"] for p in pixies.json()] == [None, None, None]


async def test_duplicate(api: Api) -> None:
    pid = (await api.http.post("/api/pixies", json={"name": "Tester"})).json()["id"]

    copied = await api.http.post(f"/api/pixies/{pid}/duplicate")
    unknown = await api.http.post("/api/pixies/nope/duplicate")

    assert copied.status_code == 201
    assert (copied.json()["name"], copied.json()["slug"]) == ("Tester 2", "tester-2")
    assert copied.json()["position"] == 1
    assert unknown.status_code == 404


async def test_a_project_chat_calls_pixies_and_teams(api: Api, tmp_path: Path) -> None:
    api.provider.script(reply("planned"))
    await api.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
    tid = (await api.http.post("/api/pixie-teams", json={"name": "QA"})).json()["id"]
    lead = (await api.http.post("/api/pixies", json={"name": "Lead", "soul": "You plan."})).json()
    await api.http.patch(f"/api/pixies/{lead['id']}", json={"team_id": tid})

    created = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "@qa check it", "mode": "in_place"}
    )
    await reach(api, created.json()["id"], "idle", results=1)
    run = api.provider.runs[0]

    assert list(run.spec.subagents) == ["lead"]
    assert run.spec.subagents["lead"].description == "Lead: You plan."
    assert run.inputs[0].text.startswith(
        "@qa check it\n\n(The user called the team @qa, a team of pixies set up in harness."
        " Its members are these subagents: lead (leader). First use the subagent lead "
    )
    assert created.json()["prompt"] == "@qa check it"
