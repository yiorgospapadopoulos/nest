import gc
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from harness.events import types
from harness.gitops.runner import CommandError
from harness.sessions.store import SessionStore
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import hang
from tests.fake_runner import PR_URL, check_run, pr_json
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git, init_repo, with_origin
from tests.test_api_review import (
    approvals,
    approve,
    event_types,
    exists,
    finished_with_changes,
)
from tests.test_api_sessions import create, reach

PASSED = [check_run("unit"), check_run("lint", conclusion="FAILURE")]


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(repo)})
        yield running


async def session_of(api: Api, session_id: str) -> dict[str, Any]:
    return (await api.http.get(f"/api/sessions/{session_id}")).json()


async def opened(api: Api, view: str | None = None) -> str:
    """A session whose work was approved and opened as a pull request, read once."""
    api.runner.pr_view = view
    session_id = await finished_with_changes(api)
    approved = await approve(api, session_id)
    assert approved.status_code == 200, approved.text
    await until(lambda: len(api.runner.gh_calls("view")) >= 1)
    if view is not None:

        async def read() -> bool:
            return (await session_of(api, session_id))["pr"] is not None

        await until(read)
    return session_id


def merge_calls(api: Api) -> list[tuple[str, ...]]:
    return api.runner.gh_calls("merge")


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/prs"),
        ("POST", "/api/sessions/x/merge"),
        ("POST", "/api/sessions/x/pr/refresh"),
    ],
)
async def test_pr_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_an_opened_pull_request_gets_a_summary_status_and_merge_approval(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=[check_run("unit")]))

    session = await session_of(api, session_id)
    assert session["pr_summary"] == "Fixed the bug.\n1 file changed, +1 -0"
    assert session["pr"]["number"] == 7
    assert session["pr"]["checks"]["state"] == "success"
    assert session["pr"]["checks"]["items"] == [
        {"name": "unit", "state": "success", "url": "https://ci.example/unit"}
    ]
    merges = [a for a in await approvals(api, status="pending") if a["kind"] == "merge"]
    assert [(m["session_id"], m["payload"]["number"]) for m in merges] == [(session_id, 7)]
    assert types.SESSION_PR in await event_types(api, session_id)


async def test_the_list_of_pull_requests(api: Api) -> None:
    session_id = await opened(api, pr_json())

    listed = (await api.http.get("/api/prs")).json()
    of_repo = (await api.http.get("/api/prs", params={"repo": "repo"})).json()
    other = (await api.http.get("/api/prs", params={"repo": "other"})).json()
    merged = (await api.http.get("/api/prs", params={"state": "merged"})).json()
    every = (await api.http.get("/api/prs", params={"state": "all"})).json()
    bad = await api.http.get("/api/prs", params={"state": "draft"})

    (item,) = listed
    assert {k: v for k, v in item.items() if k != "pr"} == {
        "session_id": session_id,
        "repo": "repo",
        "session_title": "Do it",
        "session_state": "idle",
        "url": PR_URL,
        "summary": "Fixed the bug.\n1 file changed, +1 -0",
    }
    assert item["pr"]["state"] == "open"
    assert of_repo == listed == every
    assert other == merged == []
    assert bad.status_code == 422


async def test_a_pull_request_not_read_yet_lists_as_open(api: Api) -> None:
    session_id = await opened(api)

    (item,) = (await api.http.get("/api/prs")).json()

    assert (item["session_id"], item["pr"]) == (session_id, None)
    assert (await api.http.get("/api/prs", params={"state": "closed"})).json() == []


async def test_merging_squashes_closes_the_session_and_removes_the_worktree(api: Api) -> None:
    session_id = await opened(api, pr_json())
    before = await session_of(api, session_id)
    api.runner.pr_view = pr_json(state="MERGED")

    merged = await api.http.post(f"/api/sessions/{session_id}/merge")

    assert merged.status_code == 200, merged.text
    session = merged.json()
    assert session["state"] == "closed"
    assert session["pr"]["state"] == "merged"
    assert merge_calls(api) == [
        (
            *("gh", "pr", "merge", PR_URL, "--repo", "me/repo", "--squash", "--delete-branch"),
            *("--match-head-commit", "abc123"),
        )
    ]
    assert not exists(before["worktree_path"])
    repo = api.ctx.repos.get("repo").path
    assert before["branch"] not in git(repo, "branch", "--list")
    (merge,) = [a for a in await approvals(api) if a["kind"] == "merge"]
    assert (merge["status"], merge["resolution"]) == (
        "resolved",
        {"action": "merged", "method": "squash"},
    )
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    (event,) = [e for e in events if e["type"] == types.PR_MERGED]
    assert event["payload"] == {"url": PR_URL, "method": "squash"}
    # Nothing reads a merged pull request again.
    assert (await api.http.get("/api/prs")).json() == []


async def test_merge_options_and_an_unread_pull_request(api: Api) -> None:
    session_id = await opened(api)

    merged = await api.http.post(
        f"/api/sessions/{session_id}/merge", json={"method": "rebase", "delete_branch": False}
    )

    assert merged.status_code == 200, merged.text
    assert merged.json()["state"] == "closed"
    # GitHub could not be read after the merge either, so no status is known.
    assert merged.json()["pr"] is None
    assert merge_calls(api) == [("gh", "pr", "merge", PR_URL, "--repo", "me/repo", "--rebase")]
    # IMP-13: a session's lock lives only while it is held.
    gc.collect()
    assert len(api.ctx.prs._locks) == 0  # pyright: ignore[reportPrivateUsage]


async def test_after_a_merge_an_unreadable_status_is_marked_merged(api: Api) -> None:
    session_id = await opened(api, pr_json())
    api.runner.pr_view = None

    merged = await api.http.post(f"/api/sessions/{session_id}/merge", json={"method": "merge"})

    assert merged.json()["pr"]["state"] == "merged"
    assert merge_calls(api)[0][6] == "--merge"


@pytest.mark.parametrize(
    ("failure", "stderr"),
    [
        (
            CommandError(["gh"], 1, "Pull request is not mergeable\n"),
            "Pull request is not mergeable\n",
        ),
        (FileNotFoundError("No such file: 'gh'"), "No such file: 'gh'"),
        (
            CommandError(["gh"], 1, "failed to reach https://me:ghp_secret@github.com/me/r\n"),
            "failed to reach https://github.com/me/r\n",
        ),
    ],
)
async def test_a_failed_merge_changes_nothing(api: Api, failure: Exception, stderr: str) -> None:
    session_id = await opened(api, pr_json())
    api.runner.failures["gh pr merge"] = failure

    response = await api.http.post(f"/api/sessions/{session_id}/merge")

    assert response.status_code == 502
    assert response.json() == {
        "detail": f"git merge failed: {stderr.strip()}",
        "step": "merge",
        "stderr": stderr,
    }
    session = await session_of(api, session_id)
    assert session["state"] == "idle"
    assert exists(session["worktree_path"])
    (merge,) = [a for a in await approvals(api) if a["kind"] == "merge"]
    assert merge["status"] == "pending"
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    assert {"step": "merge", "stderr": stderr} in [
        e["payload"] for e in events if e["type"] == types.GIT_FAILED
    ]
    # A retry works.
    retried = await api.http.post(f"/api/sessions/{session_id}/merge")
    assert retried.json()["state"] == "closed"


async def test_merge_needs_a_pull_request(api: Api) -> None:
    session_id = await finished_with_changes(api)

    merged = await api.http.post(f"/api/sessions/{session_id}/merge")
    refreshed = await api.http.post(f"/api/sessions/{session_id}/pr/refresh")

    expected = {"detail": f"session {session_id!r} has no pull request"}
    assert (merged.status_code, merged.json()) == (409, expected)
    assert (refreshed.status_code, refreshed.json()) == (409, expected)
    assert (await api.http.post("/api/sessions/nope/merge")).status_code == 404


async def test_a_closed_pull_request_cannot_be_merged(api: Api) -> None:
    session_id = await opened(api, pr_json(state="CLOSED"))

    response = await api.http.post(f"/api/sessions/{session_id}/merge")

    assert (response.status_code, response.json()) == (
        409,
        {"detail": "the pull request is already closed"},
    )
    assert merge_calls(api) == []


async def test_a_working_session_is_not_merged(api: Api) -> None:
    api.provider.script(hang())
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "running")
    await SessionStore(api.ctx.db, api.ctx.clock).update(session_id, pr_url=PR_URL)

    response = await api.http.post(f"/api/sessions/{session_id}/merge")

    assert response.status_code == 409
    assert "is working" in response.json()["detail"]
    assert merge_calls(api) == []


async def test_merging_a_closed_session_leaves_it_closed(api: Api) -> None:
    session_id = await opened(api, pr_json())
    await api.http.delete(f"/api/sessions/{session_id}")

    merged = await api.http.post(f"/api/sessions/{session_id}/merge")

    assert merged.status_code == 200, merged.text
    assert merged.json()["state"] == "closed"
    assert len(merge_calls(api)) == 1


async def test_a_worktree_that_cannot_be_removed_leaves_the_session_open(api: Api) -> None:
    session_id = await opened(api, pr_json())
    worktree = (await session_of(api, session_id))["worktree_path"]
    git(api.ctx.repos.get("repo").path, "worktree", "lock", worktree)

    merged = await api.http.post(f"/api/sessions/{session_id}/merge")

    assert merged.status_code == 200, merged.text
    assert merged.json()["state"] == "idle"
    assert merged.json()["pr"]["state"] == "open"
    assert exists(worktree)


async def test_refresh_reads_the_pull_request_now(api: Api) -> None:
    session_id = await opened(api)
    api.runner.pr_view = pr_json(statusCheckRollup=PASSED)

    refreshed = await api.http.post(f"/api/sessions/{session_id}/pr/refresh")

    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["pr"]["checks"]["state"] == "failure"
    api.runner.pr_view = None
    failed = await api.http.post(f"/api/sessions/{session_id}/pr/refresh")
    assert failed.status_code == 502
    assert "could not reach GitHub" in failed.json()["detail"]


async def test_failed_checks_notify_and_the_merge_card_can_be_dismissed(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=PASSED))
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    texts = [e["payload"]["text"] for e in events if e["type"] == types.NOTIFY]
    assert "CI failed: lint" in texts

    api.runner.pr_view = pr_json()
    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")
    (merge,) = [a for a in await approvals(api, status="pending") if a["kind"] == "merge"]
    dismissed = await api.http.post(f"/api/approvals/{merge['id']}/resolve", json={"dismiss": True})

    assert dismissed.json()["resolution"] == {"dismissed": True}
