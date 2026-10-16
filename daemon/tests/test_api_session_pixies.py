"""A chat's pixies over the API: calls, continuing, Send away, member calls refused (B46)."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.events import types
from nestd.providers.base import AgentTask, TextBlock, ToolResultBlock, ToolUseBlock
from tests.api_client import Api, running_api
from tests.fake_provider import messages, reply, tasks
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import reach

CALL = ToolUseBlock(
    id="a1", name="Agent", input={"subagent_type": "scribe", "prompt": "Pick an animal"}
)
HANDBACK = ToolResultBlock(
    tool_use_id="a1", content="ok\n\n[Subagent hand-back]\nagentId: ae74d5437db4d1c8d"
)
SEND = ToolUseBlock(
    id="s1", name="SendMessage", input={"to": "ae74d5437db4d1c8d", "message": "Which one?"}
)


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def pixie(api: Api, name: str, team_id: str | None = None) -> str:
    pixie_id = (await api.http.post("/api/pixies", json={"name": name})).json()["id"]
    if team_id is not None:
        await api.http.patch(f"/api/pixies/{pixie_id}", json={"team_id": team_id})
    return pixie_id


async def chat(api: Api, prompt: str) -> str:
    response = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": prompt, "mode": "in_place"}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/sessions/x/pixies"),
        ("POST", "/api/sessions/x/pixies/send-away"),
        ("GET", "/api/sessions/x/pixies/p/calls"),
        ("GET", "/api/sessions/x/agents/a1/transcript"),
        ("GET", "/api/pixie-groups"),
    ],
)
async def test_chat_pixie_routes_need_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_a_pixie_tagged_again_continues_where_it_left_off(api: Api) -> None:
    scribe = await pixie(api, "Scribe")
    api.provider.script(
        messages(
            ([CALL], None),
            ([TextBlock(text="picked")], "a1"),
            ([HANDBACK], None),
            then=reply("It picked one."),
        ),
        messages(
            ([SEND], None),
            ([ToolResultBlock(tool_use_id="s1", content='{"success":true}')], None),
            then=tasks(
                AgentTask(task_id="ae74d5437db4d1c8d", phase="started", tool_use_id="s1"),
                then=messages(
                    ([TextBlock(text="platypus")], "a1"),
                    then=tasks(
                        AgentTask(
                            task_id="ae74d5437db4d1c8d",
                            phase="finished",
                            tool_use_id="s1",
                            status="completed",
                            summary="platypus",
                        ),
                        then=reply("A platypus."),
                    ),
                ),
            ),
        ),
    )
    session_id = await chat(api, "@scribe pick an animal")
    await reach(api, session_id, "idle", results=1)
    first = (await api.http.get(f"/api/sessions/{session_id}/pixies")).json()

    await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "@scribe which?"})
    await reach(api, session_id, "idle", results=2)
    group = (await api.http.get(f"/api/sessions/{session_id}/pixies")).json()
    calls = (await api.http.get(f"/api/sessions/{session_id}/pixies/{scribe}/calls")).json()
    transcript = await api.http.get(f"/api/sessions/{session_id}/agents/a1/transcript")
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()

    (entry,) = first
    assert (entry["kind"], entry["pixie_id"], entry["state"]) == ("pixie", scribe, "done")
    assert entry["calls"][0]["agent_id"] == "ae74d5437db4d1c8d"
    run = api.provider.runs[0]
    assert [i.text for i in run.inputs] == [
        "@scribe pick an animal",
        "@scribe which?\n\n(@scribe was called earlier in this chat as agent ae74d5437db4d1c8d."
        " Continue that agent with SendMessage to 'ae74d5437db4d1c8d' instead of starting a"
        " new one.)",
    ]
    # The chat shows only what was typed.
    shown = [e["payload"]["text"] for e in events if e["type"] == types.SESSION_USER_MESSAGE]
    assert shown == ["@scribe pick an animal", "@scribe which?"]
    assert [(c["tool_use_id"], c["continued"], c["state"]) for c in group[0]["calls"]] == [
        ("s1", True, "done"),
        ("a1", False, "done"),
    ]
    assert [(c["prompt"], c["report"]) for c in calls] == [
        ("Which one?", "platypus"),
        ("Pick an animal", HANDBACK.content),
    ]
    assert [[b["text"] for b in m["blocks"]] for m in calls[0]["messages"]] == [["platypus"]]
    assert transcript.status_code == 200
    assert transcript.json()["prompt"] == "Pick an animal"
    assert any(e["type"] == types.SESSION_PIXIES for e in events)


async def test_send_away_over_the_api(api: Api) -> None:
    await pixie(api, "Scribe")
    api.provider.script(messages(([CALL], None), ([HANDBACK], None), then=reply("ok")))
    session_id = await chat(api, "@scribe go")
    await reach(api, session_id, "idle", results=1)
    base = f"/api/sessions/{session_id}/pixies"

    neither = await api.http.post(f"{base}/send-away", json={})
    both = await api.http.post(f"{base}/send-away", json={"pixie_id": "p", "team_id": "t"})
    extra = await api.http.post(f"{base}/send-away", json={"pixie_id": "p", "other": 1})
    unknown = await api.http.post("/api/sessions/nope/pixies/send-away", json={"pixie_id": "p"})
    team = await api.http.post(f"{base}/send-away", json={"team_id": "no-team"})
    scribe = (await api.http.get(base)).json()[0]["pixie_id"]
    sent = await api.http.post(f"{base}/send-away", json={"pixie_id": scribe})

    assert [r.status_code for r in (neither, both, extra)] == [422, 422, 422]
    assert unknown.status_code == 404
    assert len(team.json()) == 1
    assert (sent.status_code, sent.json()) == (200, [])
    assert (await api.http.get(base)).json() == []


async def test_every_chats_group_at_once(api: Api) -> None:
    await pixie(api, "Scribe")
    api.provider.script(messages(([CALL], None), ([HANDBACK], None), then=reply("ok")))
    kept = await chat(api, "@scribe go")
    await reach(api, kept, "idle", results=1)
    api.provider.script(messages(([CALL], None), ([HANDBACK], None), then=reply("ok")))
    sent = await chat(api, "@scribe go too")
    await reach(api, sent, "idle", results=1)
    api.provider.script(reply("hi"))
    plain = await chat(api, "hello")
    await reach(api, plain, "idle", results=1)
    scribe = (await api.http.get(f"/api/sessions/{sent}/pixies")).json()[0]["pixie_id"]
    await api.http.post(f"/api/sessions/{sent}/pixies/send-away", json={"pixie_id": scribe})

    groups = (await api.http.get("/api/pixie-groups")).json()

    # Only chats with a pixie in their group, each as `GET .../pixies` gives it.
    assert groups == {kept: (await api.http.get(f"/api/sessions/{kept}/pixies")).json()}
    assert groups[kept][0]["pixie_id"] == scribe


async def test_chat_pixie_reads_of_unknown_chats_and_calls(api: Api) -> None:
    api.provider.script(reply("hi"))
    session_id = await chat(api, "hello")
    await reach(api, session_id, "idle", results=1)

    assert (await api.http.get("/api/sessions/nope/pixies")).status_code == 404
    assert (await api.http.get("/api/sessions/nope/pixies/p/calls")).status_code == 404
    assert (await api.http.get(f"/api/sessions/{session_id}/pixies/p/calls")).json() == []
    assert (await api.http.get("/api/sessions/nope/agents/a1/transcript")).status_code == 404
    missing = await api.http.get(f"/api/sessions/{session_id}/agents/a1/transcript")
    assert missing.status_code == 404


async def test_a_team_member_is_called_only_with_its_team(api: Api) -> None:
    team = (await api.http.post("/api/pixie-teams", json={"name": "QA", "handle": "qa"})).json()
    await pixie(api, "Lead", team["id"])
    await pixie(api, "Bugs", team["id"])
    api.provider.script(reply("hi"))

    created = await api.http.post(
        "/api/sessions", json={"repo": "repo", "prompt": "@bugs look", "mode": "in_place"}
    )
    session_id = await chat(api, "@qa look")
    await reach(api, session_id, "idle", results=1)
    sent = await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "@lead hi"})

    refusal = {"detail": "Bugs is in @qa; call the team or a solo copy", "code": "pixie_in_team"}
    assert (created.status_code, created.json()) == (422, refusal)
    assert (sent.status_code, sent.json()["code"]) == (422, "pixie_in_team")
    assert sent.json()["detail"] == "Lead is in @qa; call the team or a solo copy"
    assert "It is called only as part of a team call to @qa." in (
        api.provider.runs[0].spec.subagents["bugs"].description
    )
