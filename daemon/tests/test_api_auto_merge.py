"""Merge once the checks pass (B149): GitHub's auto-merge when GitHub waits for required
checks, else Nest merges when it sees the pull request ready.
"""

from typing import Any

import pytest

from nestd.gitops.runner import CommandError
from tests.api_client import Api
from tests.async_support import until
from tests.fake_runner import PR_URL, check_run, pr_json
from tests.test_api_prs import api, merge_calls, opened, session_of
from tests.test_api_review import approvals

__all__ = ["api"]

pytestmark = pytest.mark.loops

RUNNING = [check_run("unit", status="IN_PROGRESS", conclusion="")]
PASSED = [check_run("unit")]
SQUASH_AT_HEAD = (
    *("gh", "pr", "merge", PR_URL, "--repo", "me/repo", "--squash"),
    *("--match-head-commit", "abc123"),
)


async def auto_merge(api: Api, session_id: str, **body: object) -> dict[str, Any]:
    response = await api.http.patch(
        f"/api/sessions/{session_id}/pr/auto-merge", json={"enabled": True, **body}
    )
    assert response.status_code == 200, response.text
    return response.json()


async def merge_approvals(api: Api) -> list[dict[str, Any]]:
    return [a for a in await approvals(api, status="pending") if a["kind"] == "merge"]


async def test_nest_merges_once_the_checks_pass_without_asking_again(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=RUNNING, mergeStateStatus="UNSTABLE"))

    session = await auto_merge(api, session_id)

    # GitHub would merge at once a pull request whose checks are not required.
    assert merge_calls(api) == []
    assert session["merge_when_ready"] == {
        "method": "squash",
        "delete_branch": False,
        "head": "abc123",
    }
    api.runner.pr_view = pr_json(statusCheckRollup=PASSED)
    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")
    await until(lambda: len(merge_calls(api)) == 1)
    assert merge_calls(api) == [SQUASH_AT_HEAD]
    assert await merge_approvals(api) == []


async def test_github_auto_merge_is_used_when_github_waits_for_required_checks(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=RUNNING, mergeStateStatus="BLOCKED"))
    auto = {"mergeMethod": "SQUASH", "enabledAt": "2026-01-01T12:00:00Z"}
    api.runner.pr_view = pr_json(
        statusCheckRollup=RUNNING, mergeStateStatus="BLOCKED", autoMergeRequest=auto
    )

    session = await auto_merge(api, session_id)

    assert merge_calls(api) == [(*SQUASH_AT_HEAD, "--auto")]
    assert session["pr"]["auto_merge"]["method"] == "squash"
    # Checks passed: GitHub merges by itself, so Nest neither merges nor asks.
    api.runner.pr_view = pr_json(statusCheckRollup=PASSED, autoMergeRequest=auto)
    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")
    assert merge_calls(api) == [(*SQUASH_AT_HEAD, "--auto")]
    assert await merge_approvals(api) == []


async def test_a_repository_without_auto_merge_leaves_it_to_nest(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=RUNNING, mergeStateStatus="BLOCKED"))
    api.runner.failures["gh pr merge"] = CommandError(["gh"], 1, "Auto merge is not allowed\n")

    session = await auto_merge(api, session_id, method="rebase")

    assert session["merge_when_ready"]["method"] == "rebase"
    api.runner.pr_view = pr_json(statusCheckRollup=PASSED)
    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")
    await until(lambda: len(merge_calls(api)) == 2)
    assert merge_calls(api)[1][6] == "--rebase"


async def test_a_ready_pull_request_is_merged_at_once(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=PASSED), movable=True)
    api.runner.pr_view = pr_json(state="MERGED")

    session = await auto_merge(api, session_id)

    assert session["pr"]["state"] == "merged"
    assert merge_calls(api) == [SQUASH_AT_HEAD]


async def test_turning_it_off_stops_github_auto_merge(api: Api) -> None:
    auto = {"mergeMethod": "MERGE", "enabledAt": "2026-01-01T12:00:00Z"}
    session_id = await opened(api, pr_json(statusCheckRollup=RUNNING, autoMergeRequest=auto))
    api.runner.pr_view = pr_json(statusCheckRollup=RUNNING)

    response = await api.http.patch(
        f"/api/sessions/{session_id}/pr/auto-merge", json={"enabled": False}
    )

    assert response.status_code == 200, response.text
    assert response.json()["merge_when_ready"] is None
    assert response.json()["pr"]["auto_merge"] is None
    assert merge_calls(api) == [
        ("gh", "pr", "merge", PR_URL, "--repo", "me/repo", "--disable-auto")
    ]


async def test_a_merge_that_fails_when_ready_leaves_the_merge_approval(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=RUNNING, mergeStateStatus="UNSTABLE"))
    await auto_merge(api, session_id)
    api.runner.failures["gh pr merge"] = CommandError(["gh"], 1, "Base branch was modified\n")
    api.runner.pr_view = pr_json(statusCheckRollup=PASSED)

    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")

    async def offered() -> bool:
        return len(await merge_approvals(api)) == 1

    await until(offered)
    assert (await session_of(api, session_id))["state"] == "idle"


async def test_new_commits_after_turning_it_on_need_the_merge_approval(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=RUNNING, mergeStateStatus="UNSTABLE"))
    await auto_merge(api, session_id)
    # Someone pushed after the user said yes: those commits were never approved.
    api.runner.pr_view = pr_json(statusCheckRollup=PASSED, headRefOid="def456")

    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")

    async def offered() -> bool:
        return len(await merge_approvals(api)) == 1

    await until(offered)
    assert merge_calls(api) == []
    assert (await session_of(api, session_id))["merge_when_ready"] is None


async def test_new_commits_stop_github_auto_merge(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=RUNNING, mergeStateStatus="BLOCKED"))
    auto = {"mergeMethod": "SQUASH", "enabledAt": "2026-01-01T12:00:00Z"}
    api.runner.pr_view = pr_json(
        statusCheckRollup=RUNNING, mergeStateStatus="BLOCKED", autoMergeRequest=auto
    )
    await auto_merge(api, session_id)
    api.runner.pr_view = pr_json(
        statusCheckRollup=RUNNING,
        mergeStateStatus="BLOCKED",
        autoMergeRequest=auto,
        headRefOid="def456",
    )

    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")

    disable = ("gh", "pr", "merge", PR_URL, "--repo", "me/repo", "--disable-auto")
    await until(lambda: disable in merge_calls(api))
    assert merge_calls(api) == [(*SQUASH_AT_HEAD, "--auto"), disable]
    assert (await session_of(api, session_id))["merge_when_ready"] is None
