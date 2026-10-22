"""B59: pending messages (Send now, remove), rewinding the conversation, and forks."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.events import types
from nestd.providers.base import ForkPoint, ToolResultBlock, ToolUseBlock
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import echoed, edit, messages, reply, until_interrupted
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_review import approvals
from tests.test_api_sessions import create, notified, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        running.provider.steering = True
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def events(api: Api, session_id: str) -> list[dict[str, Any]]:
    return (await api.http.get(f"/api/sessions/{session_id}/events")).json()


async def user_messages(api: Api, session_id: str) -> list[int]:
    return [e["id"] for e in await events(api, session_id) if e["type"] == "session.user_message"]


async def running_with_pending(api: Api) -> tuple[str, str]:
    """A chat whose turn runs until stopped, with one message written into it."""
    api.provider.script(until_interrupted(), reply("sent now"))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "running")
    await until(lambda: bool(api.provider.runs) and bool(api.provider.runs[0].inputs))
    await until(lambda: api.ctx.sessions.busy(session_id) and _given(api, session_id))
    sent = await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "pending"})
    return session_id, sent.json()["queued_message"]["id"]


def _given(api: Api, session_id: str) -> bool:
    live = api.ctx.sessions._live[session_id]  # pyright: ignore[reportPrivateUsage]
    return live.task is None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/sessions/s/queue/m/send-now"),
        ("POST", "/api/sessions/s/fork"),
    ],
)
async def test_the_new_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_a_pending_message_is_shown_sent_and_sent_now(api: Api) -> None:
    session_id, message_id = await running_with_pending(api)
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()

    response = await api.http.post(f"/api/sessions/{session_id}/queue/{message_id}/send-now")
    await reach(api, session_id, "idle", results=2)

    assert detail["queued"] == [
        {
            "id": message_id,
            "text": "pending",
            "attachments": [],
            "created_at": detail["queued"][0]["created_at"],
            "sent": True,
        }
    ]
    assert response.status_code == 202
    assert [i.text for i in api.provider.runs[0].inputs] == ["Do it", "pending"]


async def test_send_now_of_an_unknown_message_is_404(api: Api) -> None:
    session_id, _ = await running_with_pending(api)

    response = await api.http.post(f"/api/sessions/{session_id}/queue/nope/send-now")

    assert response.status_code == 404


async def test_a_message_claude_already_read_cannot_be_removed(api: Api) -> None:
    session_id, message_id = await running_with_pending(api)
    api.provider.runs[0].steered.clear()

    response = await api.http.delete(f"/api/sessions/{session_id}/queue/{message_id}")

    assert response.status_code == 409
    assert response.json()["code"] == "message_taken"


async def two_turns(api: Api) -> tuple[str, int, int]:
    api.provider.script(echoed("cp-1", reply("one")), echoed("cp-2", reply("two")))
    api.provider.fork_points = {("sdk-1", "cp-2"): ForkPoint("a-1")}
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle", results=1)
    await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "second"})
    await reach(api, session_id, "idle", results=2)
    # The turn's "finished" notice lands just after the idle state; wait so it is not new.
    await notified(api, session_id, "finished", count=2)
    first, second = await user_messages(api, session_id)
    return session_id, first, second


async def test_rewinding_the_conversation_gives_the_message_back(api: Api) -> None:
    session_id, _, second = await two_turns(api)
    url = f"/api/sessions/{session_id}/rewind"
    last = await api.ctx.bus.last_id()

    preview = await api.http.get(url, params={"message": second, "restore": "conversation"})
    rewound = await api.http.post(url, json={"message": second, "restore": "conversation"})

    expected: dict[str, object] = {
        "can_rewind": True,
        "files_changed": [],
        "insertions": 0,
        "deletions": 0,
        "error": None,
        "restore": "conversation",
        "text": "second",
        "attachments": [],
    }
    assert (preview.status_code, preview.json()) == (200, expected)
    assert (rewound.status_code, rewound.json()) == (200, expected)
    after = await events(api, session_id)
    assert all(e["id"] < second for e in after if e["type"] != types.SESSION_REWOUND)
    assert after[-1]["type"] == types.SESSION_REWOUND
    assert after[-1]["payload"] == {
        "message": second,
        "through": last,
        "text": "second",
        "attachments": [],
    }
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert "fork_from" not in detail


async def test_an_unknown_restore_is_refused(api: Api) -> None:
    response = await api.http.post(
        "/api/sessions/s/rewind", json={"message": 1, "restore": "everything"}
    )

    assert response.status_code == 422


async def test_a_fork_is_created_with_the_message_for_its_composer(api: Api) -> None:
    session_id, _, second = await two_turns(api)

    response = await api.http.post(f"/api/sessions/{session_id}/fork", json={"message": second})

    assert response.status_code == 201
    body = response.json()
    assert body["text"] == "second"
    assert body["attachments"] == []
    assert body["session"]["title"].endswith(" (fork)")
    assert body["session"]["state"] == "idle"
    assert "fork_at" not in body["session"]
    fork_id = body["session"]["id"]
    assert [e["type"] for e in await events(api, fork_id)][-3:] == [
        "session.user_message",
        "session.message",
        "session.result",
    ]


async def test_a_fork_of_a_message_without_a_checkpoint_is_refused(api: Api) -> None:
    api.provider.script(reply("one"))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle", results=1)
    (message,) = await user_messages(api, session_id)

    response = await api.http.post(f"/api/sessions/{session_id}/fork", json={"message": message})

    assert response.status_code == 409
    assert response.json()["code"] == "cannot_rewind"


async def test_restoring_files_brings_the_review_up_to_date(api: Api, tmp_path: Path) -> None:
    """B56: the changes bar follows the work; files restored to nothing withdraw it."""
    api.provider.script(echoed("cp-1", edit({"fix.txt": "fixed\n"}, reply("Fixed."))))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle", results=1)
    await notified(api, session_id, "review_ready")
    (message,) = await user_messages(api, session_id)
    assert len(await approvals(api, status="pending")) == 1
    (tmp_path / "repo" / "fix.txt").unlink()  # what Claude Code's restore does

    response = await api.http.post(
        f"/api/sessions/{session_id}/rewind", json={"message": message, "restore": "code"}
    )

    assert response.status_code == 200
    assert await approvals(api, status="pending") == []


async def test_rewinding_the_conversation_keeps_the_review_and_the_task_list_follows(
    api: Api,
) -> None:
    api.provider.script(
        echoed("cp-1", edit({"fix.txt": "fixed\n"}, reply("Fixed."))),
        echoed(
            "cp-2",
            messages(
                (
                    [
                        ToolUseBlock(
                            id="toolu_c1",
                            name="TaskCreate",
                            input={"subject": "Plan", "description": "", "activeForm": "Planning"},
                        )
                    ],
                    None,
                ),
                (
                    [
                        ToolResultBlock(
                            tool_use_id="toolu_c1", content="Task #1 created successfully: Plan"
                        )
                    ],
                    None,
                ),
                then=reply("Planned."),
            ),
        ),
    )
    api.provider.fork_points = {("sdk-1", "cp-2"): ForkPoint("a-1")}
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle", results=1)
    await notified(api, session_id, "review_ready")
    await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "hi"})
    await reach(api, session_id, "idle", results=2)
    _, second = await user_messages(api, session_id)
    (review,) = await approvals(api, status="pending")
    before = (await api.http.get(f"/api/sessions/{session_id}")).json()

    response = await api.http.post(
        f"/api/sessions/{session_id}/rewind", json={"message": second, "restore": "conversation"}
    )

    assert response.status_code == 200
    assert [a["id"] for a in await approvals(api, status="pending")] == [review["id"]]
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert [t["subject"] for t in before["tasks"]] == ["Plan"]
    assert detail["tasks"] == []


async def test_a_pending_message_claude_has_not_read_is_removed(api: Api) -> None:
    session_id, message_id = await running_with_pending(api)

    response = await api.http.delete(f"/api/sessions/{session_id}/queue/{message_id}")

    assert response.status_code == 204
    assert (await api.http.get(f"/api/sessions/{session_id}")).json()["queued"] == []
