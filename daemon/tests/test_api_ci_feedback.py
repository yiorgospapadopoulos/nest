"""IMP-08: `POST /api/sessions/{id}/ci-feedback` sends the failing checks' logs to the agent."""

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.events import types
from tests.api_client import Api, running_api
from tests.fake_provider import reply
from tests.fake_runner import actions_job, check_run, pr_json
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo, with_origin
from tests.test_api_prs import opened
from tests.test_api_sessions import create, reach

TOKEN = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(repo)})
        yield running


def log_lines(count: int) -> str:
    return "".join(f"test\tRun tests\t2026-10-13T10:00:00Z line {n}\n" for n in range(count))


async def sent_text(api: Api, session_id: str) -> str:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return [e for e in events if e["type"] == types.SESSION_USER_MESSAGE][-1]["payload"]["text"]


async def test_route_requires_a_device_token(api: Api) -> None:
    response = await api.http.post(
        "/api/sessions/x/ci-feedback", headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 401


async def test_the_failing_checks_logs_go_to_the_agent(api: Api) -> None:
    checks = [
        check_run("unit"),
        check_run("test", conclusion="FAILURE", url=actions_job(11)),
        check_run("lint", conclusion="TIMED_OUT", url=actions_job(12)),
        check_run("deploy-preview", conclusion="FAILURE"),
    ]
    session_id = await opened(api, pr_json(statusCheckRollup=checks))
    api.runner.job_logs = {
        "11": log_lines(200),
        "12": f"\x1b[31merror\x1b[0m pushing to https://user:{TOKEN}@github.com/me/repo\n",
    }
    api.provider.script(reply("Fixing the tests."))

    sent = await api.http.post(f"/api/sessions/{session_id}/ci-feedback")
    await reach(api, session_id, "idle", results=2)

    assert sent.status_code == 202, sent.text
    assert sent.json()["id"] == session_id
    text = await sent_text(api, session_id)
    assert text.startswith("The pull request's checks failed:")
    # The last 150 lines of each failed job.
    assert "line 50\n" in text
    assert "line 49\n" not in text
    assert "line 199" in text
    # Without color codes or credentials.
    assert "\x1b" not in text
    assert TOKEN not in text
    assert "user:" not in text
    assert "error pushing to https://github.com/me/repo" in text
    # A check outside GitHub Actions has no log harness can read.
    assert "deploy-preview" in text
    assert "https://ci.example/deploy-preview" in text
    assert "unit" not in text.split("\n", 1)[1]
    calls = [call for call in api.runner.gh_calls() if call[1:3] == ("run", "view")]
    assert calls == [
        ("gh", "run", "view", "--job", "11", "--log-failed", "--repo", "me/repo"),
        ("gh", "run", "view", "--job", "12", "--log-failed", "--repo", "me/repo"),
    ]
    assert api.provider.runs[-1].inputs[-1].text == text


async def test_a_log_that_cannot_be_read_is_named(api: Api) -> None:
    checks = [check_run("test", conclusion="FAILURE", url=actions_job(11))]
    session_id = await opened(api, pr_json(statusCheckRollup=checks))
    api.provider.script(reply("Looking."))

    sent = await api.http.post(f"/api/sessions/{session_id}/ci-feedback")
    await reach(api, session_id, "idle", results=2)

    assert sent.status_code == 202
    assert "could not read the log (HTTP 404: Not Found)" in await sent_text(api, session_id)


async def test_a_check_of_another_repository_is_not_read(api: Api) -> None:
    """SEC-18: only logs of the pull request's own repository are read."""
    elsewhere = "https://github.com/other/private/actions/runs/99/job/22"
    checks = [
        check_run("sneaky", conclusion="FAILURE", url=elsewhere),
        check_run("test", conclusion="FAILURE", url=actions_job(11).replace("me/repo", "Me/Repo")),
    ]
    session_id = await opened(api, pr_json(statusCheckRollup=checks))
    api.runner.job_logs = {"11": "boom\n", "22": "private\n"}
    api.provider.script(reply("Looking."))

    sent = await api.http.post(f"/api/sessions/{session_id}/ci-feedback")
    await reach(api, session_id, "idle", results=2)

    assert sent.status_code == 202
    text = await sent_text(api, session_id)
    assert "private\n" not in text
    assert f"another repository than the pull request's. See {elsewhere}" in text
    assert "boom" in text
    calls = [call for call in api.runner.gh_calls() if call[1:3] == ("run", "view")]
    assert calls == [("gh", "run", "view", "--job", "11", "--log-failed", "--repo", "Me/Repo")]


async def test_nothing_failing_is_a_readable_conflict(api: Api) -> None:
    session_id = await opened(api, pr_json(statusCheckRollup=[check_run("unit")]))

    refused = await api.http.post(f"/api/sessions/{session_id}/ci-feedback")

    assert refused.status_code == 409
    assert refused.json() == {
        "detail": "No checks of this pull request are failing now.",
        "code": "no_failing_checks",
    }


async def test_a_session_without_a_pull_request(api: Api) -> None:
    api.provider.script(reply("done"))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    refused = await api.http.post(f"/api/sessions/{session_id}/ci-feedback")

    assert refused.status_code == 409
    assert "has no pull request" in refused.json()["detail"]


async def test_github_unreachable(api: Api) -> None:
    session_id = await opened(api, pr_json())
    api.runner.pr_view = None

    failed = await api.http.post(f"/api/sessions/{session_id}/ci-feedback")

    assert failed.status_code == 502
