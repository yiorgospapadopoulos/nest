import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from harness.events import types
from harness.gitops.runner import CommandError
from harness.providers.base import AgentTask, MessageBlock
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import commit, crash, edit, hang, messages, reply, tasks
from tests.fake_runner import PR_URL
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git, init_repo, with_origin
from tests.test_api_sessions import create, notified, reach
from tests.tracking_fixture import create_task, start_agent_message

APPROVE = {"commit_message": "Fix the bug"}


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(repo)})
        yield running


async def finished_with_changes(api: Api, **fields: object) -> str:
    """A session whose first turn edits a file and ends with a pending review."""
    api.provider.script(edit({"fix.txt": "fixed\n"}, reply("Fixed the bug.")))
    session_id = str((await create(api, **fields))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    return session_id


async def approvals(api: Api, **params: str) -> list[dict[str, Any]]:
    return (await api.http.get("/api/approvals", params=params)).json()


async def event_types(api: Api, session_id: str) -> list[str]:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return [e["type"] for e in events]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/sessions/x/diff"),
        ("POST", "/api/sessions/x/approve"),
        ("POST", "/api/sessions/x/reject"),
        ("POST", "/api/sessions/x/feedback"),
        ("GET", "/api/approvals"),
        ("GET", "/api/approvals/x"),
        ("POST", "/api/approvals/x/resolve"),
    ],
)
async def test_review_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_a_finished_task_is_reviewed_and_opened_as_a_pull_request(api: Api) -> None:
    session_id = await finished_with_changes(api)
    (review,) = await approvals(api, status="pending", project="repo")

    diff = await api.http.get(f"/api/sessions/{session_id}/diff")
    approved = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)
    after = await api.http.get(f"/api/approvals/{review['id']}")
    # Approving again, with nothing new, only pushes again.
    again = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert review["kind"] == "review"
    assert (review["repo"], review["title"]) == ("repo", "Do it")
    assert review["payload"] == {
        "base": git(api.ctx.repos.get("repo").path, "rev-parse", "main").strip(),
        "files": 1,
        "additions": 1,
        "deletions": 0,
        "paths": ["fix.txt"],
        "summary": "Fixed the bug.",
    }
    assert [f["path"] for f in diff.json()["files"]] == ["fix.txt"]
    assert approved.status_code == 200, approved.text
    session = approved.json()
    assert session["pr_url"] == PR_URL
    assert session["commit_sha"] == git(Path(session["cwd"]), "rev-parse", "HEAD").strip()
    assert again.json() == approved.json()
    (gh,) = api.runner.gh_calls("create")
    assert gh[gh.index("--title") + 1] == "Do it"
    assert gh[gh.index("--body") + 1] == "Do it\n\nFixed the bug."
    assert after.json()["status"] == "resolved"
    assert after.json()["resolution"] == {
        "action": "approved",
        "commit_sha": session["commit_sha"],
        "pushed": True,
        "pr_url": PR_URL,
    }
    seen = await event_types(api, session_id)
    assert seen.index(types.GIT_COMMITTED) < seen.index(types.GIT_PUSHED)
    assert seen.index(types.GIT_PUSHED) < seen.index(types.PR_OPENED)
    assert seen.count(types.GIT_COMMITTED) == 1
    assert seen[-1] == types.GIT_PUSHED


async def test_a_review_survives_a_restart_and_can_be_approved(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as first:
        await first.http.post("/api/repos", json={"path": str(repo)})
        session_id = await finished_with_changes(first)

    async with running_api(tmp_path, clock, secrets) as second:
        approved = await second.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)
        items = (await second.http.get("/api/approvals")).json()

    assert approved.status_code == 200
    assert approved.json()["pr_url"] == PR_URL
    assert [(a["kind"], a["status"]) for a in items] == [("review", "resolved")]


async def test_the_pull_request_title_and_body_can_be_given(api: Api) -> None:
    session_id = await finished_with_changes(api)

    await api.http.post(
        f"/api/sessions/{session_id}/approve",
        json={**APPROVE, "pr_title": "Better title", "pr_body": "Custom body"},
    )

    (gh,) = api.runner.gh_calls("create")
    assert gh[-4:] == ("--title", "Better title", "--body", "Custom body")


async def test_a_failed_push_keeps_the_review_and_a_retry_finishes(api: Api) -> None:
    session_id = await finished_with_changes(api)
    api.runner.failures["git push"] = CommandError(["git", "push"], 1, "denied\n")

    failed = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)
    pending = await approvals(api, status="pending")
    retried = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert failed.status_code == 502
    assert failed.json() == {
        "detail": "git push failed: denied",
        "step": "push",
        "stderr": "denied\n",
    }
    assert [a["kind"] for a in pending] == ["review"]
    assert retried.status_code == 200
    assert await approvals(api, status="pending") == []


def bare_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    git(path, "init", "-q", "--bare")
    return path


async def test_a_push_goes_only_to_the_remote_url_recorded_at_registration(
    api: Api, tmp_path: Path
) -> None:
    """D050: origin changed after registration is refused until the user confirms it."""
    session_id = await finished_with_changes(api)
    repo = api.ctx.repos.get("repo")
    elsewhere = bare_repo(tmp_path / "elsewhere.git")
    git(repo.path, "remote", "set-url", "origin", str(elsewhere))
    url = f"/api/sessions/{session_id}/approve"

    refused = await api.http.post(url, json=APPROVE)
    wrong = await api.http.post(
        url, json={**APPROVE, "confirm_remote_url": str(tmp_path / "other.git")}
    )
    confirmed = await api.http.post(url, json={**APPROVE, "confirm_remote_url": str(elsewhere)})

    assert repo.remote_url == str(tmp_path / "origin.git")
    assert refused.status_code == 409
    assert refused.json() == {
        "detail": refused.json()["detail"],
        "code": "remote_changed",
        "remote_urls": [str(elsewhere)],
        "confirmed_url": repo.remote_url,
    }
    assert (wrong.status_code, wrong.json()["code"]) == (409, "remote_changed")
    assert confirmed.status_code == 200, confirmed.text
    assert (await api.http.get("/api/repos/repo")).json()["remote_url"] == str(elsewhere)
    branch = confirmed.json()["branch"]
    assert git(elsewhere, "rev-parse", branch).strip() == confirmed.json()["commit_sha"]


async def test_a_remote_added_after_registration_needs_confirmation(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    repo = init_repo(tmp_path / "repo")
    async with running_api(tmp_path, clock, secrets) as api:
        await api.http.post("/api/repos", json={"path": str(repo)})
        origin = with_origin(repo, tmp_path / "origin.git")
        session_id = await finished_with_changes(api)
        url = f"/api/sessions/{session_id}/approve"

        refused = await api.http.post(url, json=APPROVE)
        committed = await api.http.post(url, json={**APPROVE, "push": False, "open_pr": False})
        confirmed = await api.http.post(url, json={**APPROVE, "confirm_remote_url": str(origin)})

    assert refused.status_code == 409
    assert refused.json()["code"] == "remote_not_confirmed"
    assert refused.json()["remote_urls"] == [str(origin)]
    assert refused.json()["confirmed_url"] is None
    assert committed.status_code == 200, committed.text
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["pr_url"] == PR_URL


async def test_after_approval_the_daemons_own_refs_are_not_a_violation(api: Api) -> None:
    session_id = await finished_with_changes(api)
    await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    # The agent starts a turn on its own, e.g. after a background task finished.
    api.provider.runs[0].emit(reply("background job done"))
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "finished")

    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert session["git_violation"] is False
    # The approved work is not up for review again.
    assert [a["status"] for a in await approvals(api)] == ["resolved"]


@pytest.mark.parametrize(
    ("body", "status", "detail"),
    [
        ({**APPROVE, "files": ["fix.txt"]}, 422, "in-place"),
        ({**APPROVE, "push": False}, 422, "needs push"),
        ({"commit_message": "  "}, 422, None),
        ({**APPROVE, "surprise": 1}, 422, None),
    ],
)
async def test_invalid_approvals_of_worktree_sessions(
    api: Api, body: dict[str, object], status: int, detail: str | None
) -> None:
    session_id = await finished_with_changes(api)

    response = await api.http.post(f"/api/sessions/{session_id}/approve", json=body)

    assert response.status_code == status
    if detail is not None:
        assert detail in response.json()["detail"]
    assert api.runner.calls == []


async def test_approval_and_diff_need_the_working_directory(api: Api) -> None:
    session_id = await finished_with_changes(api)
    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    shutil.rmtree(session["cwd"])

    approved = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)
    diff = await api.http.get(f"/api/sessions/{session_id}/diff")

    expected = f"the working directory of session {session_id!r} no longer exists"
    assert (approved.status_code, approved.json()) == (409, {"detail": expected})
    assert (diff.status_code, diff.json()) == (409, {"detail": expected})
    assert api.runner.calls == []
    (review,) = await approvals(api)
    assert review["status"] == "pending"


async def test_without_changes_there_is_no_review_and_nothing_to_commit(api: Api) -> None:
    api.provider.script(reply("Nothing to do."))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "finished")

    response = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert await approvals(api) == []
    assert response.status_code == 409
    assert "no changes" in response.json()["detail"]


async def test_a_git_violation_blocks_approval_until_acknowledged(api: Api) -> None:
    api.provider.script(commit(reply("I committed it myself.")))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")

    refused = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)
    accepted = await api.http.post(
        f"/api/sessions/{session_id}/approve",
        json={**APPROVE, "acknowledge_violation": True, "open_pr": False},
    )

    assert refused.status_code == 409
    assert "acknowledge_violation" in refused.json()["detail"]
    assert accepted.status_code == 200
    assert accepted.json()["commit_sha"] is not None


async def test_approval_waits_for_a_running_turn(api: Api) -> None:
    api.provider.script(hang())
    session_id = str((await create(api))["id"])
    await until(lambda: bool(api.provider.runs) and bool(api.provider.runs[0].inputs))

    response = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert response.status_code == 409
    assert "wait until its turn ends" in response.json()["detail"]


async def test_reject_discards_the_work(api: Api) -> None:
    session_id = await finished_with_changes(api)
    session = (await api.http.get(f"/api/sessions/{session_id}")).json()

    rejected = await api.http.post(f"/api/sessions/{session_id}/reject")
    again = await api.http.post(f"/api/sessions/{session_id}/reject")
    diff = await api.http.get(f"/api/sessions/{session_id}/diff")

    assert rejected.json()["state"] == "closed"
    (review,) = await approvals(api)
    assert (review["status"], review["resolution"]) == ("resolved", {"action": "rejected"})
    assert not exists(session["worktree_path"])
    assert session["branch"] not in git(api.ctx.repos.get("repo").path, "branch")
    assert again.status_code == 409
    assert diff.status_code == 409


async def test_feedback_supersedes_the_review_and_continues_the_session(api: Api) -> None:
    session_id = await finished_with_changes(api)
    api.provider.script(edit({"fix.txt": "fixed better\n"}, reply("Improved.")))

    sent = await api.http.post(
        f"/api/sessions/{session_id}/feedback", json={"text": "Handle the edge case"}
    )
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "review_ready", 2)

    assert sent.status_code == 202
    assert api.provider.runs[0].inputs[-1].text == "Handle the edge case"
    first, second = await approvals(api)
    assert first["status"] == "superseded"
    assert (second["status"], second["payload"]["summary"]) == ("pending", "Improved.")


async def test_a_newer_review_supersedes_the_pending_one(api: Api) -> None:
    session_id = await finished_with_changes(api)

    api.provider.runs[0].emit(edit({"more.txt": "x\n"}, reply("Also this.")))
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "review_ready", 2)

    assert [a["status"] for a in await approvals(api)] == ["superseded", "pending"]


async def test_in_place_sessions_commit_only_the_chosen_files(api: Api) -> None:
    repo = api.ctx.repos.get("repo").path
    api.provider.script(edit({"agent.txt": "agent\n"}, reply("Done.")))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    (repo / "mine.txt").write_text("the user's\n", encoding="utf-8")
    url = f"/api/sessions/{session_id}/approve"

    with_pr = await api.http.post(url, json=APPROVE)
    without_files = await api.http.post(url, json={**APPROVE, "open_pr": False})
    unknown = await api.http.post(
        url, json={**APPROVE, "open_pr": False, "files": ["agent.txt", "nope.txt"]}
    )
    approved = await api.http.post(url, json={**APPROVE, "open_pr": False, "files": ["agent.txt"]})

    assert with_pr.status_code == 409
    assert without_files.status_code == 422
    assert unknown.status_code == 422
    assert "nope.txt" in unknown.json()["detail"]
    assert approved.status_code == 200, approved.text
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["agent.txt"]
    assert git(repo, "status", "--porcelain").strip() == "?? mine.txt"
    assert approved.json()["pr_url"] is None
    assert api.runner.gh_calls() == []


async def test_session_detail_exposes_tasks_and_agents(api: Api) -> None:
    use, result = create_task(1, "Write tests", "Writing tests")
    api.provider.script(
        messages(
            *[(blocks_of(m), None) for m in (use, result, start_agent_message("a1"))],
            then=reply("Started."),
        )
    )
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    detail = (await api.http.get(f"/api/sessions/{session_id}")).json()
    seen = await event_types(api, session_id)

    assert [(t["id"], t["subject"], t["status"]) for t in detail["tasks"]] == [
        ("1", "Write tests", "pending")
    ]
    assert [(a["id"], a["status"]) for a in detail["agents"]] == [
        ("main", "done"),
        ("a1", "running"),
    ]
    assert types.SESSION_TASKS in seen
    assert types.SESSION_AGENTS in seen


async def test_background_work_is_followed_while_the_session_is_idle(api: Api) -> None:
    started = AgentTask(task_id="t1", phase="started", tool_use_id="a1", background=True)
    api.provider.script(
        messages(
            (blocks_of(start_agent_message("a1", run_in_background=True)), None),
            then=tasks(started, then=reply("Working in the background.")),
        )
    )
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    url = f"/api/sessions/{session_id}"

    running = (await api.http.get(url)).json()
    agents_events = len(
        [t for t in await event_types(api, session_id) if t == types.SESSION_AGENTS]
    )
    finished = AgentTask(task_id="t1", phase="finished", status="completed")
    api.provider.runs[0].emit(tasks(finished))

    async def done() -> bool:
        detail = (await api.http.get(url)).json()
        return detail["background"]["completed"] == 1

    await until(done)
    stored = (await api.http.get(f"{url}/events")).json()
    agents = [e["payload"] for e in stored if e["type"] == types.SESSION_AGENTS]

    assert running["state"] == "idle"
    assert [(a["id"], a["status"]) for a in running["agents"]] == [
        ("main", "done"),
        ("a1", "running"),
    ]
    assert (running["background"]["running"], running["background"]["completed"]) == (1, 0)
    assert len(agents) == agents_events + 1
    assert agents[-1]["background"]["items"][0]["status"] == "done"
    assert [e["type"] for e in stored[-2:]] == [types.SESSION_AGENT_TASK, types.SESSION_AGENTS]


async def test_a_failed_session_notifies(api: Api) -> None:
    api.provider.script(crash("the agent died"))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "failed")
    await notified(api, session_id, "failed")

    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    (notice,) = [e["payload"] for e in events if e["type"] == types.NOTIFY]
    assert notice == {
        "kind": "failed",
        "session_id": session_id,
        "repo": "repo",
        "title": "Do it",
        "text": "the agent died",
    }


async def test_unknown_sessions_are_404(api: Api) -> None:
    for method, path in (
        ("GET", "/api/sessions/nope/diff"),
        ("POST", "/api/sessions/nope/approve"),
        ("POST", "/api/sessions/nope/reject"),
        ("POST", "/api/sessions/nope/feedback"),
    ):
        body = {"text": "x"} if path.endswith("feedback") else APPROVE
        response = await api.http.request(method, path, json=body)
        assert response.status_code == 404, path


def exists(path: str) -> bool:
    return Path(path).exists()


def blocks_of(payload: dict[str, Any]) -> list[MessageBlock]:
    return TypeAdapter(list[MessageBlock]).validate_python(payload["blocks"])
