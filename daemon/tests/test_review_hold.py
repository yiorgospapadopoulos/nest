"""A chat is not ready while its helpers work (B133): no review, no "finished" notice."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from pydantic import JsonValue, TypeAdapter

from nestd.events import types
from nestd.providers.base import AgentTask, MessageBlock
from nestd.review import hold
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import Turn, edit, messages, reply, tasks
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo, with_origin
from tests.test_api_sessions import create, notified, reach
from tests.tracking_fixture import message, start_agent_message, tool_use

STARTED = AgentTask(
    task_id="t1", phase="started", tool_use_id="a1", task_type="local_agent", background=True
)
FINISHED = AgentTask(task_id="t1", phase="finished", status="completed")
STOPPED = AgentTask(task_id="t1", phase="finished", status="stopped")


@pytest.fixture(autouse=True)
def settle_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hold, "SETTLE_SECONDS", 0)


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(repo)})
        yield running


def blocks_of(payload: dict[str, JsonValue]) -> list[MessageBlock]:
    return TypeAdapter(list[MessageBlock]).validate_python(payload["blocks"])


def starts_a_helper(then: Turn) -> Turn:
    return messages(
        (blocks_of(start_agent_message("a1", run_in_background=True)), None),
        then=tasks(STARTED, then=then),
    )


async def notices(api: Api, session_id: str) -> list[str]:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return [e["payload"]["kind"] for e in events if e["type"] == types.NOTIFY]


async def reviews(api: Api, session_id: str) -> list[str]:
    listed = (await api.http.get("/api/approvals", params={"status": "pending"})).json()
    return [a["id"] for a in listed if a["session_id"] == session_id and a["kind"] == "review"]


async def _no_reviews(api: Api, session_id: str) -> bool:
    return await reviews(api, session_id) == []


async def say(api: Api, session_id: str, text: str) -> None:
    response = await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": text})
    assert response.status_code in (200, 202), response.text


async def test_no_review_appears_until_the_helper_ended(api: Api) -> None:
    api.provider.script(
        starts_a_helper(edit({"fix.txt": "fixed\n"}, reply("On it."))), reply("Still working.")
    )
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    # The user asks how it goes: that turn ends while the helper still works.
    await say(api, session_id, "update?")
    await reach(api, session_id, "idle", results=2)
    assert await reviews(api, session_id) == []
    assert await notices(api, session_id) == []

    api.provider.runs[0].emit(tasks(STOPPED))

    await notified(api, session_id, "review_ready")
    assert len(await reviews(api, session_id)) == 1
    assert await notices(api, session_id) == ["review_ready"]


async def test_the_turn_after_the_helper_settles_the_chat_once(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(hold, "SETTLE_SECONDS", 60)
    api.provider.script(starts_a_helper(edit({"fix.txt": "fixed\n"}, reply("On it."))))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    # As Claude Code does: a helper's end starts a turn that reads its result.
    api.provider.runs[0].emit(tasks(FINISHED, then=reply("It is done.")))

    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "review_ready")
    assert await notices(api, session_id) == ["review_ready"]


async def test_a_chat_without_changes_hears_it_finished_when_the_helper_ends(api: Api) -> None:
    api.provider.script(starts_a_helper(reply("On it.")), reply("Still working."))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    # By the second turn's end, the first one's notice would be there.
    await say(api, session_id, "update?")
    await reach(api, session_id, "idle", results=2)
    assert await notices(api, session_id) == []

    api.provider.runs[0].emit(tasks(STOPPED))

    await notified(api, session_id, "finished")
    assert await notices(api, session_id) == ["finished"]


async def test_a_pending_review_goes_while_a_helper_works_and_comes_back(api: Api) -> None:
    api.provider.script(
        edit({"fix.txt": "fixed\n"}, reply("Fixed.")),
        starts_a_helper(reply("Checking it.")),
    )
    session_id = str((await create(api))["id"])
    await notified(api, session_id, "review_ready")

    await say(api, session_id, "check it")
    await reach(api, session_id, "idle", results=2)
    # The review goes in the turn's end reaction, which runs after the idle state is stored.
    await until(lambda: _no_reviews(api, session_id))

    api.provider.runs[0].emit(tasks(STOPPED))

    await notified(api, session_id, "review_ready", count=2)
    assert len(await reviews(api, session_id)) == 1


async def test_a_message_that_continues_a_finished_helper_holds_the_review(api: Api) -> None:
    """The row of a helper continued with SendMessage is at work again."""
    again = AgentTask(
        task_id="t1", phase="started", tool_use_id="s1", task_type="local_agent", background=True
    )
    api.provider.script(
        starts_a_helper(edit({"fix.txt": "fixed\n"}, reply("On it."))),
    )
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    api.provider.runs[0].emit(tasks(FINISHED, then=tasks(again, then=reply("Asked it again."))))
    await reach(api, session_id, "idle", results=2)

    assert await reviews(api, session_id) == []
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert detail["background"]["running"] == 1

    api.provider.runs[0].emit(tasks(FINISHED))

    await notified(api, session_id, "review_ready")
    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert detail["background"]["running"] == 0


async def test_a_background_command_does_not_hold_the_review(api: Api) -> None:
    """A dev server can run for days."""
    started = AgentTask(
        task_id="c1", phase="started", tool_use_id="b1", task_type="local_bash", background=True
    )
    api.provider.script(
        messages(
            (blocks_of(message(tool_use("b1", "Bash", {"command": "serve"}))), None),
            then=tasks(started, then=edit({"fix.txt": "fixed\n"}, reply("Serving."))),
        )
    )
    session_id = str((await create(api))["id"])

    await notified(api, session_id, "review_ready")


async def test_helpers_lost_to_a_restart_settle_the_chat(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as first:
        await first.http.post("/api/repos", json={"path": str(repo)})
        first.provider.script(starts_a_helper(edit({"fix.txt": "fixed\n"}, reply("On it."))))
        session_id = str((await create(first))["id"])
        await reach(first, session_id, "idle")
        assert await reviews(first, session_id) == []

    async with running_api(tmp_path, clock, secrets) as second:
        assert len(await reviews(second, session_id)) == 1
