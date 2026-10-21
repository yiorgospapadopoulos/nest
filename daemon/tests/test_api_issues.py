"""B101: a project's open GitHub issues, and chats started from one."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from nestd.events import types
from nestd.gitops.runner import CommandError
from nestd.issues.github import parse_issue
from nestd.issues.message import issue_message
from tests.api_client import Api, running_api
from tests.fake_provider import reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import git, init_repo
from tests.github_support import REPO_URL, fixture, issue_view
from tests.test_api_sessions import reach

ISSUE_URL = "https://github.com/me/repo/issues/118"
BRANCH = "118-usage-meter-shows-the-wrong-reset"


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    init_repo(tmp_path / "repo")
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(tmp_path / "repo")})
        await running.http.patch("/api/repos/repo", json={"remote_url": REPO_URL})
        yield running


async def start(api: Api, **fields: object) -> httpx.Response:
    return await api.http.post(
        "/api/sessions", json={"repo": "repo", "issue": 118, "mode": "worktree", **fields}
    )


async def user_messages(api: Api, session_id: str) -> list[dict[str, Any]]:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return [e["payload"] for e in events if e["type"] == types.SESSION_USER_MESSAGE]


async def test_issue_routes_require_a_device_token(api: Api) -> None:
    response = await api.http.get(
        "/api/repos/repo/issues", headers={"Authorization": "Bearer wrong"}
    )

    assert response.status_code == 401


async def test_the_open_issues_of_a_project(api: Api) -> None:
    api.runner.issue_list = fixture("issue_list")

    listed = await api.http.get("/api/repos/repo/issues")
    again = await api.http.get("/api/repos/repo/issues")
    refreshed = await api.http.get("/api/repos/repo/issues", params={"refresh": "true"})

    assert listed.status_code == 200
    body = listed.json()
    assert (body["available"], body["show"]) == (True, "all")
    assert body["issues"][1] == {
        "number": 118,
        "title": "Usage meter shows the wrong reset",
        "url": ISSUE_URL,
        "labels": ["bug", "ui"],
        "comments": 1,
        "updated_at": "2026-10-19T09:00:00Z",
        "prs": [
            {"number": 131, "url": "https://github.com/me/repo/pull/131"},
            {"number": 129, "url": "https://github.com/Me/Repo/pull/129"},
        ],
        "chat": None,
    }
    assert again.json() == refreshed.json() == body
    assert len([c for c in api.runner.calls if c[1:3] == ("issue", "list")]) == 2


async def test_an_issue_names_the_chat_started_from_it(api: Api) -> None:
    api.runner.issue_list = fixture("issue_list")
    api.runner.issue_view = fixture("issue_view")
    api.provider.script(reply("On it."))
    await api.http.get("/api/repos/repo/issues")

    session_id = (await start(api)).json()["id"]
    await reach(api, session_id, "idle")
    listed = (await api.http.get("/api/repos/repo/issues")).json()["issues"]

    assert [(i["number"], i["chat"]) for i in listed] == [
        (120, None),
        (118, session_id),
        (117, None),
    ]


async def test_the_client_chooses_all_or_mine(api: Api) -> None:
    api.runner.issue_list = "[]"

    mine = await api.http.get("/api/repos/repo/issues", params={"show": "mine"})
    wrong = await api.http.get("/api/repos/repo/issues", params={"show": "assigned"})

    assert mine.json() == {"available": True, "show": "mine", "issues": []}
    assert wrong.status_code == 422
    (listed,) = [c for c in api.runner.calls if c[1:3] == ("issue", "list")]
    assert listed[-2:] == ("--assignee", "@me")


async def test_without_a_github_remote_there_are_none(api: Api) -> None:
    await api.http.patch("/api/repos/repo", json={"remote_url": None})

    listed = await api.http.get("/api/repos/repo/issues")

    assert listed.json() == {"available": False, "show": "all", "issues": []}


async def test_unknown_projects_and_failed_reads(api: Api) -> None:
    api.runner.issue_list = None

    unknown = await api.http.get("/api/repos/nope/issues")
    failed = await api.http.get("/api/repos/repo/issues")

    assert unknown.status_code == 404
    assert failed.status_code == 502
    assert failed.json() == {
        "detail": "could not read the issues of me/repo: could not reach GitHub"
    }


async def test_a_chat_from_an_issue_gets_it_as_its_first_message(api: Api) -> None:
    api.runner.issue_view = fixture("issue_view")
    api.provider.script(reply("On it."))

    created = await start(api)
    assert created.status_code == 201, created.text
    session = created.json()
    await reach(api, session["id"], "idle")
    stored = (await api.http.get(f"/api/sessions/{session['id']}")).json()

    issue = {"number": 118, "title": "Usage meter shows the wrong reset", "url": ISSUE_URL}
    assert session["title"] == "Usage meter shows the wrong reset"
    assert session["issue"] == stored["issue"] == issue
    assert session["branch"] == stored["branch"] == BRANCH
    expected = issue_message(parse_issue(fixture("issue_view")), "")
    assert stored["prompt"] == expected
    (message,) = await user_messages(api, session["id"])
    assert message["text"] == expected
    assert message["issue"] == {
        **issue,
        "labels": ["bug", "ui"],
        "comments": 1,
        "user_text": "",
        "excerpt": message["issue"]["excerpt"],
    }
    assert message["issue"]["excerpt"].startswith("The meter says it resets at 14:00")
    assert api.provider.runs[-1].inputs[0].text == expected
    views = [c for c in api.runner.calls if c[1:3] == ("issue", "view")]
    assert views[0][3:6] == ("118", "--repo", "me/repo")


async def test_the_users_own_text_comes_first_and_an_existing_branch_gets_a_number(
    api: Api, tmp_path: Path
) -> None:
    git(tmp_path / "repo", "branch", BRANCH)
    git(tmp_path / "repo", "branch", f"{BRANCH}-2")
    api.runner.issue_view = fixture("issue_view")
    api.provider.script(reply("On it."))

    created = await start(api, prompt="Start with the popover", title="Reset time")
    session = created.json()
    await reach(api, session["id"], "idle")

    assert (session["title"], session["branch"]) == ("Reset time", f"{BRANCH}-3")
    (message,) = await user_messages(api, session["id"])
    assert message["text"].startswith("Start with the popover\n\nIssue #118 from GitHub")
    assert message["issue"]["user_text"] == "Start with the popover"


async def test_an_in_place_chat_from_an_issue_stays_on_the_current_branch(api: Api) -> None:
    api.runner.issue_view = fixture("issue_view")
    api.provider.script(reply("On it."))

    created = await start(api, mode="in_place")
    session = created.json()
    await reach(api, session["id"], "idle")

    assert (session["mode"], session["branch"]) == ("in_place", None)
    assert session["issue"]["number"] == 118


async def test_a_closed_or_unreadable_issue_starts_no_chat(api: Api) -> None:
    api.runner.issue_view = issue_view(state="CLOSED")
    closed = await start(api)
    api.runner.issue_view = None
    unreadable = await start(api)
    api.runner.failures["gh issue view"] = CommandError(["gh"], 1, "GraphQL: Could not resolve")
    missing = await start(api)

    assert (closed.status_code, closed.json()) == (409, {"detail": "Issue #118 is closed."})
    assert unreadable.status_code == 502
    assert missing.json() == {
        "detail": "could not read issue #118 of me/repo: GraphQL: Could not resolve"
    }
    assert (await api.http.get("/api/sessions")).json() == []


async def test_a_project_without_a_github_remote_cannot_start_from_an_issue(api: Api) -> None:
    await api.http.patch("/api/repos/repo", json={"remote_url": None})

    refused = await start(api)

    assert refused.status_code == 422
    assert "no GitHub remote" in refused.json()["detail"]


@pytest.mark.parametrize(
    "body",
    [
        {"repo": "repo"},
        {"repo": "repo", "prompt": "  "},
        {"repo": "repo", "issue": 0},
        {"repo": "repo", "issue": -3, "prompt": "x"},
    ],
)
async def test_a_chat_needs_a_prompt_or_an_issue(api: Api, body: dict[str, object]) -> None:
    assert (await api.http.post("/api/sessions", json=body)).status_code == 422


async def test_other_chats_have_no_issue(api: Api) -> None:
    api.provider.script(reply("done"))

    created = await api.http.post("/api/sessions", json={"repo": "repo", "prompt": "Do it"})
    await reach(api, created.json()["id"], "idle")

    assert created.json()["issue"] is None
    (message,) = await user_messages(api, created.json()["id"])
    assert "issue" not in message
