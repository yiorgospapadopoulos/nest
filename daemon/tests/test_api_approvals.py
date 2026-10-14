from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from harness.providers.base import (
    PlanDecision,
    Question,
    QuestionAnswer,
    QuestionOption,
    QuestionRequest,
)
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_engine import server_info
from tests.fake_provider import ask, edit, plan, question, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, notified, reach

QUESTIONS = QuestionRequest(
    tool_use_id="toolu_q",
    questions=(
        Question(
            "Which data structure?",
            "Data Structure",
            (QuestionOption("DAG", "Dependencies", recommended=True), QuestionOption("Tree")),
            False,
        ),
        Question("Which checks?", None, (QuestionOption("Lint"), QuestionOption("Tests")), True),
    ),
)


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


async def pending(api: Api) -> dict[str, Any]:
    async def created() -> bool:
        return bool((await api.http.get("/api/approvals", params={"status": "pending"})).json())

    await until(created)
    (item,) = (await api.http.get("/api/approvals", params={"status": "pending"})).json()
    return item


async def test_questions_are_answered_through_the_queue(api: Api) -> None:
    api.provider.script(question(QUESTIONS, reply("Going with a DAG.")))
    session_id = str((await create(api, permission_mode="bypassPermissions"))["id"])
    item = await pending(api)
    await reach(api, session_id, "waiting")
    await notified(api, session_id, "question")

    incomplete = await api.http.post(
        f"/api/approvals/{item['id']}/resolve", json={"answers": {"Which data structure?": "DAG"}}
    )
    answered = await api.http.post(
        f"/api/approvals/{item['id']}/resolve",
        json={"answers": {"Which data structure?": "DAG", "Which checks?": ["Lint", "Tests"]}},
    )
    twice = await api.http.post(f"/api/approvals/{item['id']}/resolve", json={"dismiss": True})
    await reach(api, session_id, "idle")

    assert item["kind"] == "question"
    options = item["payload"]["questions"][0]["options"]
    assert options[0] == {"label": "DAG", "description": "Dependencies", "recommended": True}
    assert incomplete.status_code == 422
    assert answered.status_code == 200
    assert twice.status_code == 409
    assert api.provider.runs[0].answers == [
        QuestionAnswer({"Which data structure?": "DAG", "Which checks?": "Lint, Tests"})
    ]


async def test_a_dismissed_question_reaches_the_agent(api: Api) -> None:
    api.provider.script(question(QUESTIONS, reply("OK, my call then.")))
    session_id = str((await create(api))["id"])
    item = await pending(api)

    await api.http.post(
        f"/api/approvals/{item['id']}/resolve", json={"dismiss": True, "message": "You decide"}
    )
    await reach(api, session_id, "idle")

    assert api.provider.runs[0].answers == [QuestionAnswer(None, "You decide")]


async def test_always_allow_skips_later_prompts_for_the_tool(api: Api) -> None:
    api.provider.script(ask("Edit", ask("Edit", reply("Both edits done."))))
    session_id = str((await create(api))["id"])
    item = await pending(api)

    await api.http.post(
        f"/api/approvals/{item['id']}/resolve", json={"behavior": "allow", "always": True}
    )
    await reach(api, session_id, "idle")

    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert session["allowed_tools"] == ["Edit"]
    assert len((await api.http.get("/api/approvals")).json()) == 1
    assert [d.behavior for d in api.provider.runs[0].decisions] == ["allow", "allow"]


async def test_reviews_and_unknown_items_cannot_be_resolved_here(api: Api) -> None:
    api.provider.script(edit({"a.txt": "a\n"}, reply("Done.")))
    session_id = str((await create(api))["id"])
    await notified(api, session_id, "review_ready")
    review = await pending(api)

    as_review = await api.http.post(
        f"/api/approvals/{review['id']}/resolve", json={"behavior": "allow"}
    )
    unknown = await api.http.post("/api/approvals/nope/resolve", json={"behavior": "allow"})
    missing = await api.http.get("/api/approvals/nope")
    fetched = await api.http.get(f"/api/approvals/{review['id']}")
    bad_status = await api.http.get("/api/approvals", params={"status": "maybe"})

    assert as_review.status_code == 422
    assert "approve, reject or feedback" in as_review.json()["detail"]
    assert unknown.status_code == 404
    assert missing.status_code == 404
    assert fetched.json() == review
    assert bad_status.status_code == 422


async def test_stopping_the_daemon_expires_prompts_and_keeps_reviews(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    repo = init_repo(tmp_path / "repo")
    async with running_api(tmp_path, clock, secrets) as first:
        await first.http.post("/api/repos", json={"path": str(repo)})
        first.provider.script(edit({"a.txt": "a\n"}, reply("Done.")))
        reviewed = str((await create(first))["id"])
        await notified(first, reviewed, "review_ready")
        first.provider.script(ask("Bash", reply("never")))
        asking = str((await create(first))["id"])
        await reach(first, asking, "waiting")

    async with running_api(tmp_path, clock, secrets) as second:
        items = (await second.http.get("/api/approvals")).json()

    by_session = {item["session_id"]: item for item in items}
    assert by_session[reviewed]["status"] == "pending"
    assert by_session[asking]["status"] == "expired"
    assert by_session[asking]["resolution"] == {"reason": "the daemon stopped"}


async def test_an_approved_plan_continues_in_the_chosen_mode(api: Api) -> None:
    """Auto only with a model that supports it; the session follows the chosen mode."""
    api.engine.info = server_info("default", "opus", auto=("opus",))
    assert await api.ctx.engine.refresh()
    api.provider.script(plan("# Plan", reply("Working on it.")))
    session_id = str((await create(api, permission_mode="plan"))["id"])
    item = await pending(api)
    url = f"/api/approvals/{item['id']}/resolve"

    auto = await api.http.post(url, json={"decision": "approve", "mode": "auto"})
    bypass = await api.http.post(url, json={"decision": "approve", "mode": "bypassPermissions"})
    manual = await api.http.post(url, json={"decision": "approve", "mode": "default"})
    await reach(api, session_id, "idle")

    assert auto.status_code == 422
    assert auto.json() == {"detail": "Default does not support Auto mode"}
    assert bypass.status_code == 422
    assert manual.status_code == 200
    assert manual.json()["resolution"] == {"decision": "approve", "mode": "default"}
    assert api.provider.runs[0].plans == [PlanDecision(approved=True, mode="default")]
    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert session["permission_mode"] == "default"


async def test_a_plan_is_approved_in_auto_with_a_model_that_supports_it(api: Api) -> None:
    api.engine.info = server_info("default", "opus", auto=("opus",))
    assert await api.ctx.engine.refresh()
    api.provider.script(plan("# Plan", reply("Working on it.")))
    session_id = str((await create(api, permission_mode="plan", model="opus"))["id"])
    item = await pending(api)

    auto = await api.http.post(
        f"/api/approvals/{item['id']}/resolve", json={"decision": "approve", "mode": "auto"}
    )
    await reach(api, session_id, "idle")

    assert auto.status_code == 200
    assert api.provider.runs[0].plans == [PlanDecision(approved=True, mode="auto")]
