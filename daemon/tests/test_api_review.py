import asyncio
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from harness.events import types
from harness.gitops.runner import CommandError
from harness.providers.base import AgentTask, MessageBlock
from harness.review import watch
from harness.review.models import SessionDiff
from harness.sessions.models import SendResult
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


async def violations(api: Api, session_id: str) -> list[list[dict[str, Any]]]:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return [e["payload"]["changes"] for e in events if e["type"] == types.SESSION_GIT_VIOLATION]


async def test_refs_changed_after_the_turn_are_caught_before_publishing(api: Api) -> None:
    """SEC-01: a background command can change refs after the turn's audit (D013 layer 4)."""
    session_id = await finished_with_changes(api)
    repo = api.ctx.repos.get("repo").path
    origin = repo.parent / "origin.git"
    sha = git(repo, "rev-parse", "HEAD").strip()
    git(repo, "update-ref", "refs/heads/sneaky", "HEAD")
    url = f"/api/sessions/{session_id}/approve"

    refused = await api.http.post(url, json=APPROVE)
    flagged = (await api.http.get(f"/api/sessions/{session_id}")).json()
    pushed_before = git(origin, "for-each-ref")
    again = await api.http.post(url, json=APPROVE)
    accepted = await api.http.post(url, json={**APPROVE, "acknowledge_violation": True})

    assert refused.status_code == 409
    assert "acknowledge_violation" in refused.json()["detail"]
    assert flagged["git_violation"] is True
    assert "agent/" not in pushed_before
    assert again.status_code == 409
    # Reported once: the second check compares with the refs the first one saw.
    assert await violations(api, session_id) == [
        [{"ref": "refs/heads/sneaky", "before": None, "after": sha}]
    ]
    assert accepted.status_code == 200, accepted.text


async def test_a_moved_head_is_caught_before_publishing(api: Api) -> None:
    session_id = await finished_with_changes(api)
    worktree = Path(str((await api.http.get(f"/api/sessions/{session_id}")).json()["cwd"]))
    elsewhere = git(worktree, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "x").strip()
    git(worktree, "update-ref", "--no-deref", "HEAD", elsewhere)

    refused = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert refused.status_code == 409
    assert [change["ref"] for (change,) in await violations(api, session_id)] == ["HEAD"]


async def test_a_fetch_between_the_turn_and_approve_waits_for_the_next_turn_end(
    api: Api,
) -> None:
    """Only HEAD and local branches decide what is pushed; a fetch (yours, or an editor's)
    does not block approve, and the next turn-end audit still reports it (D013 layer 4).
    """
    session_id = await finished_with_changes(api)
    repo = api.ctx.repos.get("repo").path
    fetched = git(repo, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "upstream").strip()
    before = git(repo, "rev-parse", "refs/remotes/origin/main").strip()
    git(repo, "update-ref", "refs/remotes/origin/main", fetched)
    git(repo, "tag", "fetched-tag", fetched)

    approved = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert approved.status_code == 200, approved.text
    assert approved.json()["git_violation"] is False
    assert await violations(api, session_id) == []
    api.provider.runs[0].emit(reply("background job done"))
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "finished")
    assert await violations(api, session_id) == [
        [
            {"ref": "refs/remotes/origin/main", "before": before, "after": fetched},
            {"ref": "refs/tags/fetched-tag", "before": None, "after": fetched},
        ]
    ]


async def test_an_agent_cannot_turn_an_approved_push_into_a_mirror_push(api: Api) -> None:
    """SEC-01 end to end: the agent switches the checkout to a branch named `--mirror`
    after its turn; approving reports that and, even when acknowledged, pushes nothing.
    """
    repo = api.ctx.repos.get("repo").path
    origin = repo.parent / "origin.git"
    git(repo, "push", "-q", "origin", "main:refs/heads/secret")
    api.provider.script(edit({"agent.txt": "agent\n"}, reply("Done.")))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    git(repo, "update-ref", "refs/heads/--mirror", "HEAD")
    git(repo, "symbolic-ref", "HEAD", "refs/heads/--mirror")
    before = git(origin, "for-each-ref")
    body = {**APPROVE, "open_pr": False, "files": ["agent.txt"]}
    url = f"/api/sessions/{session_id}/approve"

    refused = await api.http.post(url, json=body)
    acknowledged = await api.http.post(url, json={**body, "acknowledge_violation": True})

    assert refused.status_code == 409
    assert "acknowledge_violation" in refused.json()["detail"]
    assert [change["ref"] for (change,) in await violations(api, session_id)] == [
        "refs/heads/--mirror"
    ]
    assert acknowledged.status_code == 409
    assert acknowledged.json()["code"] == "unsafe_branch"
    assert git(origin, "for-each-ref") == before
    (review,) = await approvals(api)
    assert review["status"] == "pending"


async def test_refs_changed_while_publishing_are_reported_after_the_next_turn(api: Api) -> None:
    """Only the daemon's own commit and push are taken into the audit's baseline."""
    session_id = await finished_with_changes(api)
    repo = api.ctx.repos.get("repo").path
    api.runner.before["git push"] = lambda: git(repo, "update-ref", "refs/heads/sneaky", "HEAD")
    approved = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    api.provider.runs[0].emit(reply("background job done"))
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "finished")

    assert approved.status_code == 200, approved.text
    assert [change["ref"] for (change,) in await violations(api, session_id)] == [
        "refs/heads/sneaky"
    ]


async def test_work_of_an_agent_that_never_started_is_published_without_a_violation(
    api: Api,
) -> None:
    """No audit ran before, so the refs as they are now become the baseline."""
    api.provider.open_error = RuntimeError("the agent could not start")
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "failed")
    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    (Path(session["cwd"]) / "fix.txt").write_text("by hand\n", encoding="utf-8")

    approved = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert approved.status_code == 200, approved.text
    assert approved.json()["git_violation"] is False
    assert await violations(api, session_id) == []


async def test_a_message_sent_while_the_work_is_published_runs_after_it(api: Api) -> None:
    """BUG-14: nothing edits the tree between the commit and the push."""
    session_id = await finished_with_changes(api)
    (run,) = api.provider.runs
    api.provider.script(reply("Sent after the push."))
    sent: list[SendResult] = []

    async def meanwhile() -> None:
        sent.append(await api.ctx.sessions.send(session_id, "while pushing", []))
        await asyncio.sleep(0.05)
        assert len(run.inputs) == 1

    api.runner.before["git push"] = meanwhile
    approved = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)
    await reach(api, session_id, "idle", results=2)

    assert approved.status_code == 200, approved.text
    (result,) = sent
    assert result.queued_message is not None
    assert [i.text for i in run.inputs] == ["Do it", "while pushing"]
    assert await api.ctx.sessions.queued(session_id) == []


async def test_a_turn_the_agent_starts_while_the_work_is_published_waits(api: Api) -> None:
    session_id = await finished_with_changes(api)
    (run,) = api.provider.runs

    async def meanwhile() -> None:
        run.emit(reply("Started on my own."))
        await asyncio.sleep(0.05)

    api.runner.before["git push"] = meanwhile
    approved = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)
    await reach(api, session_id, "idle", results=2)

    assert approved.status_code == 200, approved.text
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    kinds = [
        e["payload"]["state"] if e["type"] == types.SESSION_STATE else e["type"]
        for e in events
        if e["type"] in (types.SESSION_STATE, types.GIT_PUSHED)
    ]
    assert kinds[-4:] == ["idle", types.GIT_PUSHED, "running", "idle"]


async def test_a_message_sent_as_a_turn_ends_supersedes_its_review(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-18: the review is made before the next message starts, never during its turn."""
    entered, release = asyncio.Event(), asyncio.Event()
    real_diff = watch.session_diff

    async def slow_diff(cwd: Path, base: str | None) -> SessionDiff:
        entered.set()
        await release.wait()
        return await real_diff(cwd, base)

    monkeypatch.setattr(watch, "session_diff", slow_diff)
    api.provider.script(edit({"fix.txt": "fixed\n"}, reply("Fixed the bug.")), hang())
    session_id = str((await create(api))["id"])
    await asyncio.wait_for(entered.wait(), 5)

    sending = asyncio.create_task(
        api.http.post(f"/api/sessions/{session_id}/messages", json={"text": "and more"})
    )
    await asyncio.sleep(0.05)
    started_early = len(api.provider.runs[0].inputs) > 1
    release.set()
    sent = await sending
    await until(lambda: len(api.provider.runs[0].inputs) == 2)

    assert sent.status_code == 202
    assert not started_early
    assert [a["status"] for a in await approvals(api)] == ["superseded"]


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


async def test_background_work_a_killed_daemon_left_running_is_stopped_on_start(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    """B-19: the agent's process ended with the daemon, so nothing it ran still runs."""
    repo = init_repo(tmp_path / "repo")
    started = AgentTask(task_id="t1", phase="started", tool_use_id="a1", background=True)
    async with running_api(tmp_path, clock, secrets) as first:
        await first.http.post("/api/repos", json={"path": str(repo)})
        first.provider.script(
            messages(
                (blocks_of(start_agent_message("a1", run_in_background=True)), None),
                then=tasks(started, then=reply("Working in the background.")),
            )
        )
        session_id = str((await create(first))["id"])
        await reach(first, session_id, "idle")
        before = (await first.http.get(f"/api/sessions/{session_id}")).json()

    async with running_api(tmp_path, clock, secrets) as second:
        after = (await second.http.get(f"/api/sessions/{session_id}")).json()
        events = (await second.http.get(f"/api/sessions/{session_id}/events")).json()

    assert before["background"]["running"] == 1
    assert after["background"]["running"] == 0
    assert [i["status"] for i in after["background"]["items"]] == ["failed"]
    assert [e["type"] for e in events[-2:]] == [types.SESSION_AGENT_TASK, types.SESSION_AGENTS]
    assert events[-2]["payload"]["status"] == "stopped"
    assert events[-1]["payload"]["background"]["running"] == 0


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
