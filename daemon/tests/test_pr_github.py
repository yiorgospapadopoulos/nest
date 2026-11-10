import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from nestd.prs.github import fetch_status, parse_status, repo_of, summarize_checks
from nestd.prs.models import PrCheck
from tests.fake_runner import PR_URL, FakeRunner, check_run, pr_json

NOW = datetime(2026, 1, 1, 13, 0, tzinfo=UTC)


def status_context(context: str, state: str) -> object:
    return {"__typename": "StatusContext", "context": context, "state": state, "targetUrl": ""}


def test_an_open_pull_request_without_checks() -> None:
    status = parse_status(pr_json(), NOW)

    assert status.model_dump() == {
        "number": 7,
        "url": PR_URL,
        "title": "Do it",
        "state": "open",
        "checks": {"state": "none", "passed": 0, "failed": 0, "pending": 0, "items": []},
        "mergeable": True,
        "merge_state": "clean",
        "review_decision": None,
        "head_sha": "abc123",
        "created_at": datetime(2026, 1, 1, 12, 0, tzinfo=UTC),
        "base_branch": None,
        "auto_merge": None,
        "changed_at": NOW,
        "updated_at": NOW,
    }
    assert status.ready_to_merge()
    assert not status.blocked()


def test_the_real_output_of_a_closed_sandbox_pull_request() -> None:
    # Recorded from `gh pr view 1 -R example/demo-repo --json ...`.
    output = (
        '{"createdAt":"2026-10-06T15:45:25Z","headRefOid":"779f15c948adfad4f0d9a987a30fb1e033a52983",'
        '"mergeStateStatus":"CLEAN","mergeable":"MERGEABLE","number":1,"reviewDecision":"",'
        '"state":"CLOSED","statusCheckRollup":[],"title":"Add hello greeting (Nest live test)",'
        '"url":"https://github.com/example/demo-repo/pull/1"}'
    )

    status = parse_status(output, NOW)

    assert (status.number, status.state, status.checks.state) == (1, "closed", "none")
    assert status.blocked()
    assert not status.ready_to_merge()


@pytest.mark.parametrize(
    ("state", "expected"), [("OPEN", "open"), ("MERGED", "merged"), ("CLOSED", "closed")]
)
def test_states(state: str, expected: str) -> None:
    assert parse_status(pr_json(state=state), NOW).state == expected


@pytest.mark.parametrize(
    ("mergeable", "expected"), [("MERGEABLE", True), ("CONFLICTING", False), ("UNKNOWN", None)]
)
def test_mergeable(mergeable: str, expected: bool | None) -> None:
    assert parse_status(pr_json(mergeable=mergeable), NOW).mergeable is expected


def test_check_runs_and_commit_statuses_are_mapped() -> None:
    rollup = [
        check_run("lint"),
        check_run("docs", conclusion="SKIPPED"),
        check_run("style", conclusion="NEUTRAL"),
        check_run("unit", conclusion="FAILURE"),
        check_run("slow", conclusion="TIMED_OUT"),
        check_run("build", status="IN_PROGRESS", conclusion=""),
        status_context("ci/legacy", "SUCCESS"),
        status_context("ci/queued", "PENDING"),
        status_context("ci/expected", "EXPECTED"),
        status_context("ci/broken", "ERROR"),
    ]

    status = parse_status(pr_json(statusCheckRollup=rollup), NOW)

    assert [(item.name, item.state) for item in status.checks.items] == [
        ("lint", "success"),
        ("docs", "skipped"),
        ("style", "skipped"),
        ("unit", "failure"),
        ("slow", "failure"),
        ("build", "pending"),
        ("ci/legacy", "success"),
        ("ci/queued", "pending"),
        ("ci/expected", "pending"),
        ("ci/broken", "failure"),
    ]
    assert status.checks.items[0].url == "https://ci.example/lint"
    assert status.checks.items[-1].url is None
    assert (status.checks.passed, status.checks.failed, status.checks.pending) == (4, 3, 3)
    assert status.checks.state == "failure"
    assert status.failing_checks() == ["unit", "slow", "ci/broken"]


@pytest.mark.parametrize(
    ("states", "expected"),
    [
        ([], "none"),
        (["success", "skipped"], "success"),
        (["skipped"], "success"),
        (["success", "pending"], "pending"),
        (["pending", "failure"], "failure"),
    ],
)
def test_the_checks_state(states: list[str], expected: str) -> None:
    items = [PrCheck.model_validate({"name": s, "state": s, "url": None}) for s in states]

    assert summarize_checks(items).state == expected


def test_missing_optional_fields_read_as_unknown() -> None:
    output = json.dumps({"number": 3, "url": PR_URL, "title": "t", "state": "OPEN"})

    status = parse_status(output, NOW)

    assert status.mergeable is None
    assert (status.merge_state, status.review_decision, status.head_sha) == (None, None, None)
    assert status.created_at is None
    assert status.checks.state == "none"
    assert not status.ready_to_merge()
    assert not status.blocked()


@pytest.mark.parametrize(
    ("fields", "ready", "blocked"),
    [
        ({"mergeStateStatus": "BEHIND"}, True, False),
        ({"mergeStateStatus": "UNSTABLE"}, True, False),
        ({"mergeStateStatus": "BLOCKED"}, False, True),
        ({"mergeStateStatus": "DIRTY", "mergeable": "CONFLICTING"}, False, True),
        ({"mergeStateStatus": "DRAFT"}, False, True),
        ({"mergeable": "UNKNOWN", "mergeStateStatus": "UNKNOWN"}, False, False),
        ({"statusCheckRollup": [check_run("ci", status="QUEUED", conclusion="")]}, False, True),
        ({"statusCheckRollup": [check_run("ci")]}, True, False),
        ({"reviewDecision": "CHANGES_REQUESTED"}, True, False),
        ({"state": "MERGED"}, False, True),
    ],
)
def test_ready_and_blocked(fields: dict[str, object], ready: bool, blocked: bool) -> None:
    status = parse_status(pr_json(**fields), NOW)

    assert (status.ready_to_merge(), status.blocked()) == (ready, blocked)


def test_review_decisions_are_lower_case() -> None:
    status = parse_status(pr_json(reviewDecision="REVIEW_REQUIRED"), NOW)

    assert status.review_decision == "review_required"


def test_garbled_output_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        parse_status("not json", NOW)


def test_same_as_ignores_when_nest_looked() -> None:
    first = parse_status(pr_json(), NOW)
    later = parse_status(pr_json(), datetime(2026, 1, 2, tzinfo=UTC))
    changed = parse_status(pr_json(headRefOid="def456"), NOW)

    assert first.same_as(later)
    assert not first.same_as(changed)


async def test_fetch_status_asks_gh_for_the_fields(tmp_path: Path) -> None:
    runner = FakeRunner()
    runner.pr_view = pr_json()

    status = await fetch_status(runner, PR_URL, tmp_path, NOW)

    assert status.number == 7
    (call,) = runner.calls
    assert call[:4] == ("gh", "pr", "view", PR_URL)
    assert call[4] == "--json"
    assert set(call[5].split(",")) == {
        "state",
        "mergeable",
        "mergeStateStatus",
        "statusCheckRollup",
        "reviewDecision",
        "baseRefName",
        "autoMergeRequest",
        "headRefOid",
        "url",
        "number",
        "title",
        "createdAt",
    }


def test_repo_of_a_pull_request_url() -> None:
    assert repo_of("https://github.com/owner/name/pull/7") == "owner/name"


def test_auto_merge_and_the_base_branch_are_read() -> None:
    auto: dict[str, object] = {
        "mergeMethod": "REBASE",
        "enabledAt": "2026-01-01T12:00:00Z",
        "enabledBy": {},
    }

    status = parse_status(pr_json(baseRefName="feature", autoMergeRequest=auto), NOW)

    assert status.base_branch == "feature"
    assert status.auto_merge is not None
    assert status.auto_merge.method == "rebase"
