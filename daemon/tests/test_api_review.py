import asyncio
import gc
import shutil
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import TypeAdapter

from nestd.events import types
from nestd.gitops.runner import CommandError
from nestd.issues.models import IssueRef
from nestd.providers.base import AgentTask, MessageBlock
from nestd.review import watch
from nestd.review.models import SessionDiff
from nestd.sessions.models import SendResult
from nestd.sessions.store import SessionStore
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import (
    FakeRun,
    Turn,
    background,
    commit,
    crash,
    edit,
    hang,
    messages,
    reply,
    tasks,
)
from tests.fake_runner import PR_URL
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import commit_file, git, init_repo, with_origin
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


async def approve(api: Api, session_id: str, body: dict[str, Any] = APPROVE) -> httpx.Response:
    """Approve with the fingerprint of the review as it is now, as a client sends it after
    loading the review; a body's own fingerprint is sent as it is.
    """
    if "expected_fingerprint" not in body:
        diff = await api.http.get(f"/api/sessions/{session_id}/diff")
        fingerprint = diff.json()["fingerprint"] if diff.status_code == 200 else ""
        body = {**body, "expected_fingerprint": fingerprint}
    return await api.http.post(f"/api/sessions/{session_id}/approve", json=body)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/sessions/x/diff"),
        ("POST", "/api/sessions/x/approve"),
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
    approved = await approve(api, session_id, APPROVE)
    after = await api.http.get(f"/api/approvals/{review['id']}")
    # Approving again, with nothing new, only pushes again.
    again = await approve(api, session_id, APPROVE)

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
        approved = await approve(second, session_id, APPROVE)
        items = (await second.http.get("/api/approvals")).json()

    assert approved.status_code == 200
    assert approved.json()["pr_url"] == PR_URL
    assert [(a["kind"], a["status"]) for a in items] == [("review", "resolved")]


async def test_the_pull_request_title_and_body_can_be_given(api: Api) -> None:
    session_id = await finished_with_changes(api)

    await approve(
        api,
        session_id,
        {**APPROVE, "pr_title": "Better title", "pr_body": "Custom body"},
    )

    (gh,) = api.runner.gh_calls("create")
    assert gh[-4:] == ("--title", "Better title", "--body", "Custom body")
    # IMP-13: a session's lock lives only while it is held.
    gc.collect()
    assert len(api.ctx.reviews._locks) == 0  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize(
    ("pr_body", "body"),
    [
        (None, "Usage meter\n\nFixed the bug.\n\nCloses #118"),
        ("Custom body", "Custom body\n\nCloses #118"),
        ("Fixes #118 for good", "Fixes #118 for good"),
    ],
)
async def test_the_pull_request_of_a_chat_from_an_issue_closes_it(
    api: Api, pr_body: str | None, body: str
) -> None:
    session_id = await finished_with_changes(api, title="Usage meter")
    store = SessionStore(api.ctx.db, api.ctx.clock)
    issue = IssueRef(number=118, title="Usage meter", url="https://github.com/me/repo/issues/118")
    await store.update(session_id, issue=issue)

    approved = await approve(api, session_id, {**APPROVE, "pr_body": pr_body})

    assert approved.status_code == 200, approved.text
    (gh,) = api.runner.gh_calls("create")
    assert gh[gh.index("--body") + 1] == body
    # IMP-13: a session's lock lives only while it is held.
    gc.collect()
    assert len(api.ctx.reviews._locks) == 0  # pyright: ignore[reportPrivateUsage]


async def test_a_failed_push_keeps_the_review_and_a_retry_finishes(api: Api) -> None:
    session_id = await finished_with_changes(api)
    api.runner.failures["git push"] = CommandError(["git", "push"], 1, "denied\n")

    failed = await approve(api, session_id, APPROVE)
    pending = await approvals(api, status="pending")
    retried = await approve(api, session_id, APPROVE)

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

    refused = await approve(api, session_id, APPROVE)
    wrong = await approve(
        api, session_id, {**APPROVE, "confirm_remote_url": str(tmp_path / "other.git")}
    )
    confirmed = await approve(api, session_id, {**APPROVE, "confirm_remote_url": str(elsewhere)})

    assert repo.remote_url == str(tmp_path / "origin.git")
    assert refused.status_code == 409
    assert_readable(refused.json()["detail"])
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

        refused = await approve(api, session_id, APPROVE)
        committed = await approve(api, session_id, {**APPROVE, "push": False, "open_pr": False})
        confirmed = await approve(api, session_id, {**APPROVE, "confirm_remote_url": str(origin)})

    assert refused.status_code == 409
    assert refused.json()["code"] == "remote_not_confirmed"
    assert_readable(refused.json()["detail"])
    assert refused.json()["remote_urls"] == [str(origin)]
    assert refused.json()["confirmed_url"] is None
    assert committed.status_code == 200, committed.text
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["pr_url"] == PR_URL


async def test_after_approval_the_approved_work_is_not_reviewed_again(api: Api) -> None:
    session_id = await finished_with_changes(api)
    await approve(api, session_id, APPROVE)

    # The agent starts a turn on its own, e.g. after a background task finished.
    api.provider.runs[0].emit(reply("background job done"))
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "finished")

    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    assert "git_violation" not in session
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

    response = await approve(api, session_id, body)

    assert response.status_code == status
    if detail is not None:
        assert detail in response.json()["detail"]
    assert api.runner.calls == []


async def test_approval_and_diff_need_the_working_directory(api: Api) -> None:
    session_id = await finished_with_changes(api)
    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    shutil.rmtree(session["cwd"])

    approved = await approve(api, session_id, APPROVE)
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

    response = await approve(api, session_id, APPROVE)

    assert await approvals(api) == []
    assert response.status_code == 409
    assert "no changes" in response.json()["detail"]


async def test_a_commit_of_all_the_work_leaves_nothing_to_review(api: Api) -> None:
    """B58: the user asked Claude to commit; that is no violation and needs no review."""
    api.provider.script(commit(reply("Committed.")))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "finished")

    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    diff = (await api.http.get(f"/api/sessions/{session_id}/diff")).json()
    refused = await approve(api, session_id, APPROVE)

    assert await approvals(api) == []
    assert "git_violation" not in session
    assert diff["files"] == []
    assert "commits" not in diff
    assert diff["base"] == diff["head"]["commit"] != session["base_ref"]
    assert refused.status_code == 409
    assert "no changes" in refused.json()["detail"]
    origin = api.ctx.repos.get("repo").path.parent / "origin.git"
    assert "agent/" not in git(origin, "for-each-ref")


async def test_approving_after_the_agents_own_commit_publishes_both(api: Api) -> None:
    """B58: the review shows only what is left uncommitted; the worktree's branch is pushed
    with the agent's commit and Nest's, and the pull request opened from it.
    """
    api.provider.script(commit(edit({"fix.txt": "fixed\n"}, reply("Committed part."))))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    worktree = await session_cwd(api, session_id)
    agents = git(worktree, "rev-parse", "HEAD").strip()

    (review,) = await approvals(api, status="pending")
    approved = await approve(api, session_id, APPROVE)
    origin = api.ctx.repos.get("repo").path.parent / "origin.git"
    branch = approved.json()["branch"]

    assert review["payload"]["paths"] == ["fix.txt"]
    assert review["payload"]["base"] == agents
    assert approved.status_code == 200, approved.text
    assert approved.json()["pr_url"] == PR_URL
    pushed = git(origin, "rev-parse", f"refs/heads/{branch}").strip()
    assert pushed == approved.json()["commit_sha"]
    assert git(worktree, "rev-parse", "HEAD^").strip() == agents
    assert git(worktree, "show", "--name-only", "--format=", "HEAD").split() == ["fix.txt"]


API_FIELDS = (
    "confirm_remote_url",
    "expected_fingerprint",
    "expected_head",
    "open_pr",
)


def assert_readable(detail: str) -> None:
    """Approve refusals are shown to the user as they are: no API field names in them."""
    assert detail
    for field in API_FIELDS:
        assert field not in detail, (field, detail)


def commit_behind_the_review(cwd: Path, name: str = "extra.txt") -> str:
    """A commit made with plumbing and put on the checkout's branch while its files stay
    out of the working tree, as a process the agent left running could (SEC-02).
    """
    (cwd / name).write_text("unreviewed\n", encoding="utf-8")
    git(cwd, "add", name)
    tree = git(cwd, "write-tree").strip()
    git(cwd, "rm", "-q", "--cached", name)
    (cwd / name).unlink()
    sha = git(cwd, "commit-tree", tree, "-p", "HEAD", "-m", "unreviewed").strip()
    git(cwd, "update-ref", "HEAD", sha)
    return sha


async def session_cwd(api: Api, session_id: str) -> Path:
    return Path(str((await api.http.get(f"/api/sessions/{session_id}")).json()["cwd"]))


async def test_other_branches_do_not_block_approval(api: Api) -> None:
    """BUG-51: other chats' branches and the user's own commits are not this chat's work."""
    session_id = await finished_with_changes(api)
    api.provider.script(reply("Nothing to do."))
    other = str((await create(api, prompt="Another task"))["id"])
    await reach(api, other, "idle")
    repo = api.ctx.repos.get("repo").path
    commit_file(repo, "mine.txt")
    git(repo, "branch", "my-experiment")

    approved = await approve(api, session_id, APPROVE)

    assert approved.status_code == 200, approved.text


async def test_a_moved_head_is_caught_before_publishing(api: Api) -> None:
    session_id = await finished_with_changes(api)
    worktree = await session_cwd(api, session_id)
    seen = (await api.http.get(f"/api/sessions/{session_id}/diff")).json()["fingerprint"]
    elsewhere = git(worktree, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "x").strip()
    git(worktree, "update-ref", "--no-deref", "HEAD", elsewhere)

    refused = await approve(api, session_id, {**APPROVE, "expected_fingerprint": seen})

    assert (refused.status_code, refused.json()["code"]) == (409, "review_changed")
    assert api.runner.calls == []


async def test_a_branch_switch_on_the_same_commit_is_caught_before_publishing(
    api: Api,
) -> None:
    """SEC-06: an in-place push goes to the branch HEAD names, which the review shows."""
    repo = api.ctx.repos.get("repo").path
    git(repo, "branch", "deploy")
    api.provider.script(edit({"agent.txt": "agent\n"}, reply("Done.")))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    seen = (await api.http.get(f"/api/sessions/{session_id}/diff")).json()
    git(repo, "symbolic-ref", "HEAD", "refs/heads/deploy")
    body = {**APPROVE, "open_pr": False, "files": ["agent.txt"]}

    diff = (await api.http.get(f"/api/sessions/{session_id}/diff")).json()
    refused = await approve(api, session_id, {**body, "expected_fingerprint": seen["fingerprint"]})

    assert (seen["head"]["branch"], diff["head"]["branch"]) == ("main", "deploy")
    assert (refused.status_code, refused.json()["code"]) == (409, "review_changed")
    assert api.runner.calls == []


async def test_a_fetch_between_the_turn_and_approve_does_not_block_it(api: Api) -> None:
    """Only HEAD and the working tree decide what is published; a fetch (yours, or an
    editor's) changes neither.
    """
    session_id = await finished_with_changes(api)
    repo = api.ctx.repos.get("repo").path
    fetched = git(repo, "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "upstream").strip()
    git(repo, "update-ref", "refs/remotes/origin/main", fetched)
    git(repo, "tag", "fetched-tag", fetched)

    approved = await approve(api, session_id, APPROVE)

    assert approved.status_code == 200, approved.text


async def test_an_agent_cannot_turn_an_approved_push_into_a_mirror_push(api: Api) -> None:
    """SEC-01 end to end: the agent switches the checkout to a branch named `--mirror`
    after its turn; approving the review as it now shows pushes nothing.
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

    refused = await approve(api, session_id, body)

    assert refused.status_code == 409
    assert refused.json()["code"] == "unsafe_branch"
    assert_readable(refused.json()["detail"])
    assert git(origin, "for-each-ref") == before
    (review,) = await approvals(api)
    assert review["status"] == "pending"


async def test_work_of_an_agent_that_never_started_is_published(api: Api) -> None:
    api.provider.open_error = RuntimeError("the agent could not start")
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "failed")
    session = (await api.http.get(f"/api/sessions/{session_id}")).json()
    (Path(session["cwd"]) / "fix.txt").write_text("by hand\n", encoding="utf-8")

    approved = await approve(api, session_id, APPROVE)

    assert approved.status_code == 200, approved.text


async def test_the_review_shows_where_the_work_goes_and_what_is_not_committed(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    """A commit made after the review, here after a restart, moves HEAD: the review then
    compares the working tree with the new HEAD, and approving publishes on top of it (B58).
    """
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as first:
        await first.http.post("/api/repos", json={"path": str(repo)})
        session_id = await finished_with_changes(first)
        worktree = await session_cwd(first, session_id)
        clean = (await first.http.get(f"/api/sessions/{session_id}/diff")).json()
    sha = commit_file(worktree, "extra.txt")

    async with running_api(tmp_path, clock, secrets) as second:
        url = f"/api/sessions/{session_id}"
        diff = (await second.http.get(f"{url}/diff")).json()
        stale = await approve(
            second, session_id, {**APPROVE, "expected_fingerprint": clean["fingerprint"]}
        )
        accepted = await approve(second, session_id, APPROVE)
        after = (await second.http.get(f"{url}/diff")).json()

    branch = accepted.json()["branch"]
    assert clean["head"] == {"commit": clean["base"], "branch": branch}
    assert diff["head"] == {"commit": sha, "branch": branch}
    assert diff["base"] == sha
    assert [f["path"] for f in diff["files"]] == ["fix.txt"]
    assert (stale.status_code, stale.json()["code"]) == (409, "review_changed")
    assert accepted.status_code == 200, accepted.text
    assert git(worktree, "rev-parse", "HEAD^").strip() == sha
    assert after["files"] == []
    assert after["head"]["commit"] == accepted.json()["commit_sha"]


async def test_approving_twice_reviews_only_the_new_work(api: Api) -> None:
    """Approving twice, with more work in between: the second review starts at Nest's commit."""
    session_id = await finished_with_changes(api)
    url = f"/api/sessions/{session_id}"
    first = await approve(api, session_id, APPROVE)
    api.provider.script(edit({"more.txt": "more\n"}, reply("More.")))
    await api.http.post(f"{url}/feedback", json={"text": "and more"})
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "review_ready")

    between = (await api.http.get(f"{url}/diff")).json()
    second = await approve(api, session_id, APPROVE)
    after = (await api.http.get(f"{url}/diff")).json()

    assert first.status_code == 200, first.text
    assert [f["path"] for f in between["files"]] == ["more.txt"]
    assert between["head"]["commit"] == first.json()["commit_sha"]
    assert second.status_code == 200, second.text
    assert second.json()["commit_sha"] != first.json()["commit_sha"]
    assert after["files"] == []


async def test_approval_is_refused_when_head_moved_since_the_review(api: Api) -> None:
    session_id = await finished_with_changes(api)
    url = f"/api/sessions/{session_id}"
    review = (await api.http.get(f"{url}/diff")).json()
    seen = {
        "expected_head": review["head"]["commit"],
        "expected_fingerprint": review["fingerprint"],
    }
    moved_to = commit_behind_the_review(await session_cwd(api, session_id))

    moved = await approve(api, session_id, {**APPROVE, **seen})
    pending = await approvals(api, status="pending")
    again = (await api.http.get(f"{url}/diff")).json()
    approved = await approve(
        api,
        session_id,
        {
            **APPROVE,
            "expected_head": again["head"]["commit"],
            "expected_fingerprint": again["fingerprint"],
        },
    )

    # Checked before the fingerprint, which the move changed too.
    assert moved.status_code == 409
    assert moved.json() == {"detail": moved.json()["detail"], "code": "head_changed"}
    assert_readable(moved.json()["detail"])
    assert [a["kind"] for a in pending] == ["review"]
    assert again["head"]["commit"] == moved_to
    assert approved.status_code == 200, approved.text


async def test_approving_needs_the_fingerprint_of_the_review(api: Api) -> None:
    session_id = await finished_with_changes(api)

    response = await api.http.post(f"/api/sessions/{session_id}/approve", json=APPROVE)

    assert response.status_code == 422
    assert api.runner.calls == []


async def test_approval_is_refused_when_the_work_changed_since_the_review(api: Api) -> None:
    """The review fingerprint: approve publishes only the work the user saw."""
    session_id = await finished_with_changes(api)
    url = f"/api/sessions/{session_id}"
    review = (await api.http.get(f"{url}/diff")).json()
    worktree = await session_cwd(api, session_id)
    (worktree / "fix.txt").write_text("import evil\n", encoding="utf-8")
    seen = {
        "expected_head": review["head"]["commit"],
        "expected_fingerprint": review["fingerprint"],
    }

    changed = await approve(api, session_id, {**APPROVE, **seen})
    pending = await approvals(api, status="pending")
    approved = await approve(api, session_id, {**APPROVE, "expected_head": seen["expected_head"]})

    assert changed.status_code == 409
    assert changed.json() == {
        "detail": "The changes are different from the review you saw. Open the review again.",
        "code": "review_changed",
    }
    assert [a["kind"] for a in pending] == ["review"]
    assert approved.status_code == 200, approved.text
    committed = git(worktree, "show", "HEAD:fix.txt")
    assert committed == "import evil\n"


async def test_a_repository_the_agent_staged_itself_is_never_committed(api: Api) -> None:
    """SEC-14: a staged gitlink would be pushed as a submodule that points nowhere."""
    session_id = await finished_with_changes(api)
    worktree = await session_cwd(api, session_id)
    init_repo(worktree / "lib")
    git(worktree, "-c", "advice.addEmbeddedRepo=false", "add", "lib")

    diff = (await api.http.get(f"/api/sessions/{session_id}/diff")).json()
    refused = await approve(api, session_id)

    lib = next(f for f in diff["files"] if f["path"] == "lib")
    assert lib["nested_repository"] is True
    assert refused.status_code == 409
    assert refused.json() == {
        "detail": refused.json()["detail"],
        "code": "nested_repository",
        "paths": ["lib"],
    }
    assert_readable(refused.json()["detail"])
    assert git(worktree, "rev-parse", "HEAD").strip() == diff["base"]


async def in_place_review(api: Api) -> tuple[str, Path]:
    api.provider.script(edit({"agent.txt": "agent\n"}, reply("Done.")))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    return session_id, api.ctx.repos.get("repo").path


@pytest.mark.parametrize(
    ("flag", "clear"),
    [
        ("--assume-unchanged", "git update-index --no-assume-unchanged <file>"),
        ("--skip-worktree", "git update-index --no-skip-worktree <file>"),
    ],
)
async def test_files_git_is_told_to_ignore_are_never_committed(
    api: Api, flag: str, clear: str
) -> None:
    """SEC-10: `git commit -- <file>` takes the working file, while the review shows the
    staged one, which git keeps showing for such a file.
    """
    session_id, repo = await in_place_review(api)
    git(repo, "add", "agent.txt")
    git(repo, "update-index", flag, "agent.txt", "README.md")
    (repo / "agent.txt").write_text("import evil\n", encoding="utf-8")
    body = {**APPROVE, "open_pr": False, "files": ["agent.txt"]}

    refused = await approve(api, session_id, body)
    git(repo, "update-index", flag.replace("--", "--no-"), "agent.txt")
    review = (await api.http.get(f"/api/sessions/{session_id}/diff")).json()
    approved = await approve(api, session_id, body)

    assert refused.status_code == 409
    assert refused.json() == {
        "detail": refused.json()["detail"],
        "code": "index_flags",
        "paths": ["agent.txt"],
    }
    assert "agent.txt" in refused.json()["detail"]
    assert clear in refused.json()["detail"]
    assert "README.md" not in refused.json()["detail"]
    assert_readable(refused.json()["detail"])
    (agent,) = [f for f in review["files"] if f["path"] == "agent.txt"]
    assert [line["text"] for line in agent["hunks"][0]["lines"]] == ["import evil"]
    # Only the chosen files count: the user's own flags elsewhere stay as they are.
    assert approved.status_code == 200, approved.text
    assert git(repo, "show", "HEAD:agent.txt") == "import evil\n"


@pytest.mark.parametrize(
    "attributes", ["assets/.gitattributes", ".gitattributes", ".git/info/attributes"]
)
async def test_a_repository_that_uses_git_lfs_is_published_from_terminal(
    api: Api, attributes: str
) -> None:
    """PL-17: Nest runs no hooks, so git-lfs would not upload the files it stores."""
    repo = api.ctx.repos.get("repo").path
    (repo / attributes).parent.mkdir(parents=True, exist_ok=True)
    (repo / attributes).write_text("*.psd filter=lfs diff=lfs merge=lfs -text\n", encoding="utf-8")
    if not attributes.startswith(".git/"):
        git(repo, "add", attributes)
        git(repo, "commit", "-q", "-m", "lfs")
    session_id = await finished_with_changes(api)

    refused = await approve(api, session_id)

    assert refused.status_code == 409
    assert refused.json() == {"detail": refused.json()["detail"], "code": "lfs_unsupported"}
    assert "Terminal" in refused.json()["detail"]
    assert_readable(refused.json()["detail"])
    assert api.runner.calls == []


async def test_an_attribute_that_only_looks_like_lfs_is_published(api: Api) -> None:
    repo = api.ctx.repos.get("repo").path
    commit_file(repo, ".gitattributes", "*.bin filter=lfs-like\n# filter=lfs once\n")
    session_id = await finished_with_changes(api)

    approved = await approve(api, session_id)

    assert approved.status_code == 200, approved.text


async def test_approval_waits_for_background_tasks(api: Api) -> None:
    """BUG-57, SEC-07: a background task could edit the tree while it is committed."""
    session_id = await finished_with_changes(api)
    (run,) = api.provider.runs
    run.emit(background(1))
    await until(lambda: api.ctx.sessions.background_running(session_id))

    refused = await approve(api, session_id, APPROVE)
    calls = list(api.runner.calls)
    run.emit(background(0))
    await until(lambda: not api.ctx.sessions.background_running(session_id))
    approved = await approve(api, session_id, APPROVE)

    assert refused.status_code == 409
    assert refused.json() == {"detail": refused.json()["detail"], "code": "background_running"}
    assert_readable(refused.json()["detail"])
    assert calls == []
    assert approved.status_code == 200, approved.text


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
    approved = await approve(api, session_id, APPROVE)
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
    approved = await approve(api, session_id, APPROVE)
    await reach(api, session_id, "idle", results=2)

    assert approved.status_code == 200, approved.text
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    kinds = [
        e["payload"]["state"] if e["type"] == types.SESSION_STATE else e["type"]
        for e in events
        if e["type"] in (types.SESSION_STATE, types.GIT_PUSHED)
    ]
    assert kinds[-4:] == ["idle", types.GIT_PUSHED, "running", "idle"]


async def test_a_message_sent_as_a_turn_ends_waits_for_its_review(
    api: Api, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BUG-18: the review is made before the next message starts, never during its turn."""
    entered, release = asyncio.Event(), asyncio.Event()
    real_diff = watch.session_diff

    calls = 0

    async def slow_diff(cwd: Path) -> SessionDiff:
        nonlocal calls
        calls += 1
        if calls == 2:  # the first turn's end; its start came first
            entered.set()
            await release.wait()
        return await real_diff(cwd)

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
    assert [a["status"] for a in await approvals(api)] == ["pending"]


async def test_approval_waits_for_a_running_turn(api: Api) -> None:
    api.provider.script(hang())
    session_id = str((await create(api))["id"])
    await until(lambda: bool(api.provider.runs) and bool(api.provider.runs[0].inputs))

    response = await approve(api, session_id, APPROVE)

    assert response.status_code == 409
    assert "wait until its turn ends" in response.json()["detail"]


async def test_there_is_no_reject_route(api: Api) -> None:
    """B56: a review the user does not want simply waits; the chat goes on."""
    session_id = await finished_with_changes(api)

    response = await api.http.post(f"/api/sessions/{session_id}/reject")

    assert response.status_code in (404, 405)
    assert [a["status"] for a in await approvals(api)] == ["pending"]


def remove(names: list[str], then: Turn) -> Turn:
    """Deletes files in the session's working directory, as an agent undoing its work."""

    async def turn(run: FakeRun) -> None:
        for name in names:
            (Path(run.spec.cwd) / name).unlink()
        await then(run)

    return turn


async def send(api: Api, session_id: str, text: str) -> httpx.Response:
    return await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": text})


async def test_a_chat_turn_that_changes_nothing_keeps_the_review(api: Api) -> None:
    """B56: "hi" gets an answer, not a new "Ready for review"."""
    session_id = await finished_with_changes(api)
    (before,) = await approvals(api)
    api.provider.script(reply("Hello!"))

    sent = await send(api, session_id, "hi")
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "finished")

    assert sent.status_code == 202
    assert await approvals(api) == [before]


async def test_a_chat_turn_in_a_dirty_checkout_gets_no_review(api: Api) -> None:
    """The user's own uncommitted work is not the chat's turn changing anything."""
    repo = api.ctx.repos.get("repo").path
    (repo / "mine.txt").write_text("the user's\n", encoding="utf-8")
    api.provider.script(reply("Hello!"))

    session_id = str((await create(api, mode="in_place", prompt="hi"))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "finished")

    assert await approvals(api) == []


async def test_a_turn_that_undoes_the_work_withdraws_the_review(api: Api) -> None:
    session_id = await finished_with_changes(api)
    api.provider.script(remove(["fix.txt"], reply("Undone.")))

    await send(api, session_id, "undo that")
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "finished")

    assert [a["status"] for a in await approvals(api)] == ["superseded"]


async def test_sending_a_message_keeps_the_pending_review(api: Api) -> None:
    session_id = await finished_with_changes(api)
    api.provider.script(hang())

    sent = await send(api, session_id, "what did you change?")
    await reach(api, session_id, "running")

    assert sent.status_code == 202
    assert [a["status"] for a in await approvals(api)] == ["pending"]


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

    with_pr = await approve(api, session_id, APPROVE)
    without_files = await approve(api, session_id, {**APPROVE, "open_pr": False})
    unknown = await approve(
        api, session_id, {**APPROVE, "open_pr": False, "files": ["agent.txt", "nope.txt"]}
    )
    approved = await approve(api, session_id, {**APPROVE, "open_pr": False, "files": ["agent.txt"]})

    assert with_pr.status_code == 409
    assert_readable(with_pr.json()["detail"])
    assert without_files.status_code == 422
    assert unknown.status_code == 422
    assert "nope.txt" in unknown.json()["detail"]
    assert approved.status_code == 200, approved.text
    assert git(repo, "show", "--name-only", "--format=", "HEAD").split() == ["agent.txt"]
    assert git(repo, "status", "--porcelain").strip() == "?? mine.txt"
    assert approved.json()["pr_url"] is None
    assert api.runner.gh_calls() == []
    after = (await api.http.get(f"/api/sessions/{session_id}/diff")).json()
    assert after["head"] == {"commit": approved.json()["commit_sha"], "branch": "main"}
    # The user's own file stays out of the commit, so it is still in the review.
    assert [f["path"] for f in after["files"]] == ["mine.txt"]


async def test_your_own_commits_on_the_pushed_branch_go_with_the_work(api: Api) -> None:
    """In place, a push publishes every commit on the branch, the user's own included, as a
    push from Terminal would (B58).
    """
    repo = api.ctx.repos.get("repo").path
    api.provider.script(edit({"agent.txt": "agent\n"}, reply("Done.")))
    session_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, session_id, "idle")
    await notified(api, session_id, "review_ready")
    mine = commit_file(repo, "mine.txt")
    body = {**APPROVE, "open_pr": False, "files": ["agent.txt"]}

    accepted = await approve(api, session_id, body)

    assert accepted.status_code == 200, accepted.text
    assert git(repo, "rev-parse", "HEAD^").strip() == mine


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
        ("POST", "/api/sessions/nope/feedback"),
    ):
        body = (
            {"text": "x"} if path.endswith("feedback") else {**APPROVE, "expected_fingerprint": ""}
        )
        response = await api.http.request(method, path, json=body)
        assert response.status_code == 404, path


def exists(path: str) -> bool:
    return Path(path).exists()


def blocks_of(payload: dict[str, Any]) -> list[MessageBlock]:
    return TypeAdapter(list[MessageBlock]).validate_python(payload["blocks"])
