"""B101: review comments on a pull request Nest opened go back to the agent."""

import json
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from nestd.events import types
from nestd.gitops.runner import CommandError
from nestd.prs.models import PrReview
from nestd.prs.reviews import REPLY, parse_reviews
from nestd.sessions.store import SessionStore
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.fake_provider import edit, reply
from tests.fake_runner import PR_URL, pr_json
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo, with_origin
from tests.github_support import REPO_URL, fixture, review_threads, thread
from tests.test_api_prs import opened, session_of
from tests.test_api_review import approvals, approve, finished_with_changes
from tests.test_api_sessions import create, notified, reach


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    repo = init_repo(tmp_path / "repo")
    with_origin(repo, tmp_path / "origin.git")
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(repo)})
        yield running


async def reviewed(api: Api, reviews: str) -> str:
    """A session with an open pull request whose review comments were read."""
    api.runner.pr_reviews = reviews
    session_id = await opened(api, pr_json())

    async def read() -> bool:
        return (await session_of(api, session_id))["review"] is not None

    await until(read)
    return session_id


async def asks(api: Api) -> list[dict[str, Any]]:
    return [a for a in await approvals(api) if a["kind"] == "review_comments"]


async def user_messages(api: Api, session_id: str) -> list[dict[str, Any]]:
    events = (await api.http.get(f"/api/sessions/{session_id}/events")).json()
    return [e["payload"] for e in events if e["type"] == types.SESSION_USER_MESSAGE]


@pytest.mark.parametrize(
    ("method", "path"),
    [("POST", "/api/sessions/x/pr/review-feedback"), ("PATCH", "/api/sessions/x/pr/review")],
)
async def test_review_routes_require_a_device_token(api: Api, method: str, path: str) -> None:
    response = await api.http.request(method, path, headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


async def test_review_comments_wait_in_needs_you_until_sent_to_the_agent(api: Api) -> None:
    session_id = await reviewed(api, fixture("pr_review_threads"))
    session = await session_of(api, session_id)
    (ask,) = await asks(api)
    api.provider.script(reply("Fixed all three."))

    sent = await api.http.post(f"/api/sessions/{session_id}/pr/review-feedback")
    await reach(api, session_id, "idle", results=2)

    assert session["review"]["changes_requested"] is True
    assert len(session["review"]["items"]) == 3
    assert ask["payload"]["number"] == 7
    assert sent.status_code == 202, sent.text
    assert sent.json()["id"] == session_id
    message = (await user_messages(api, session_id))[-1]
    assert message["text"].startswith("Review feedback on #7, sent by Nest.")
    assert message["review_feedback"]["number"] == 7
    assert message["review_feedback"]["count"] == 3
    assert [c["path"] for c in message["review_feedback"]["comments"]] == [
        "src/usage/meter.py",
        "src/usage/old.py",
        None,
    ]
    assert api.provider.runs[-1].inputs[-1].text == message["text"]
    after = await session_of(api, session_id)
    assert after["review"]["sent"] == [item["id"] for item in session["review"]["items"]]
    (done,) = await asks(api)
    assert (done["status"], done["resolution"]) == ("resolved", {"action": "sent"})

    again = await api.http.post(f"/api/sessions/{session_id}/pr/review-feedback")
    assert again.status_code == 409
    assert again.json() == {
        "detail": "No review comments of this pull request wait to be sent.",
        "code": "no_review_comments",
    }


async def test_chosen_review_comments_are_sent_one_at_a_time(api: Api) -> None:
    two = review_threads(
        [thread("T1", ("C1", "sam", "Rename.")), thread("T2", ("C2", "ana", "Split."))], []
    )
    session_id = await reviewed(api, two)
    api.provider.script(reply("Split it."), reply("Renamed."))
    url = f"/api/sessions/{session_id}/pr/review-feedback"

    unknown = await api.http.post(url, json={"ids": ["nope"]})
    wrong = await api.http.post(url, json={"ids": ["T2:C2"], "all": True})
    one = await api.http.post(url, json={"ids": ["T2:C2", "nope"]})
    await reach(api, session_id, "idle", results=2)
    rest = await api.http.post(url, json={"ids": None})
    await reach(api, session_id, "idle", results=3)

    assert (unknown.status_code, unknown.json()["code"]) == (409, "no_review_comments")
    assert wrong.status_code == 422
    assert (one.status_code, rest.status_code) == (202, 202)
    first, second = [m["review_feedback"] for m in (await user_messages(api, session_id))[-2:]]
    assert [c["id"] for c in first["comments"]] == ["T2:C2"]
    assert [c["id"] for c in second["comments"]] == ["T1:C1"]
    assert [(a["status"], a["payload"]["comments"][0]["id"]) for a in await asks(api)] == [
        ("superseded", "T1:C1"),
        ("resolved", "T1:C1"),
    ]


async def test_a_review_comments_ask_can_be_dismissed(api: Api) -> None:
    await reviewed(api, review_threads([thread("T1", ("C1", "sam", "Rename."))], []))
    (ask,) = await asks(api)

    wrong = await api.http.post(f"/api/approvals/{ask['id']}/resolve", json={"behavior": "allow"})
    dismissed = await api.http.post(f"/api/approvals/{ask['id']}/resolve", json={"dismiss": True})

    assert wrong.status_code == 422
    assert dismissed.json()["resolution"] == {"dismissed": True}


async def test_auto_send_is_switched_on_the_session(api: Api) -> None:
    session_id = await reviewed(api, review_threads([], []))
    api.provider.script(reply("Renamed."))

    switched = await api.http.patch(
        f"/api/sessions/{session_id}/pr/review", json={"auto_send": True}
    )
    api.runner.pr_reviews = review_threads([thread("T1", ("C1", "sam", "Rename."))], [])
    await api.http.post(f"/api/sessions/{session_id}/pr/refresh")
    await reach(api, session_id, "idle", results=2)

    assert switched.status_code == 200
    assert switched.json()["review"]["auto_send"] is True
    assert (await user_messages(api, session_id))[-1]["review_feedback"]["count"] == 1
    assert await asks(api) == []
    off = await api.http.patch(f"/api/sessions/{session_id}/pr/review", json={"auto_send": False})
    assert off.json()["review"]["auto_send"] is False


async def test_a_session_without_a_pull_request_has_no_review(api: Api) -> None:
    api.provider.script(reply("done"))
    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    sent = await api.http.post(f"/api/sessions/{session_id}/pr/review-feedback")
    switched = await api.http.patch(
        f"/api/sessions/{session_id}/pr/review", json={"auto_send": True}
    )
    wrong = await api.http.patch(f"/api/sessions/{session_id}/pr/review", json={"auto": True})

    assert (sent.status_code, switched.status_code, wrong.status_code) == (409, 409, 422)
    assert (await session_of(api, session_id))["review"] is None


async def test_a_pull_request_the_agent_opened_is_followed_after_its_turn(api: Api) -> None:
    await api.http.patch("/api/repos/repo", json={"remote_url": REPO_URL})
    api.runner.pr_list = json.dumps(
        [
            {
                "headRepository": {"id": "R_1", "name": "repo"},
                "headRepositoryOwner": {"id": "U_1", "login": "me"},
                "number": 7,
                "url": PR_URL,
            }
        ]
    )
    api.runner.pr_view = pr_json()
    api.provider.script(reply("Opened the pull request."))

    session_id = str((await create(api))["id"])
    await reach(api, session_id, "idle")

    async def followed() -> bool:
        return (await session_of(api, session_id))["pr"] is not None

    await until(followed)
    session = await session_of(api, session_id)
    assert session["pr_url"] == PR_URL
    lists = [c for c in api.runner.calls if c[1:3] == ("pr", "list")]
    assert lists[0][5:7] == ("--head", session["branch"])


def replies(api: Api) -> list[tuple[str, ...]]:
    """The review thread replies Nest posted."""
    return [
        call[5:]
        for call in api.runner.calls
        if call[1:3] == ("api", "graphql") and call[4] == f"query={REPLY}"
    ]


async def edited(api: Api, session_id: str, text: str, turns: int) -> None:
    """The agent's next turn changes the work, which waits for review again."""
    api.provider.script(edit({"fix.txt": f"{text}\n"}, reply(text)))
    sent = await api.http.post(f"/api/sessions/{session_id}/messages", json={"text": text})
    assert sent.status_code == 202
    await reach(api, session_id, "idle", results=turns)
    await notified(api, session_id, "review_ready", turns)


async def test_a_push_to_the_pull_request_replies_once_on_each_thread_sent(api: Api) -> None:
    review = {
        "id": "PRR_1",
        "state": "COMMENTED",
        "body": "Also the docs.",
        "author": {"login": "sam", "__typename": "User"},
        "url": "https://github.com/me/repo/pull/7#pullrequestreview-1",
        "submittedAt": "2026-10-20T11:00:00Z",
    }
    threads = [thread("T1", ("C1", "sam", "Rename.")), thread("T2", ("C2", "ana", "Split."))]
    session_id = await reviewed(api, review_threads(threads, [review]))
    api.provider.script(edit({"fix.txt": "renamed\n"}, reply("Renamed.")))
    url = f"/api/sessions/{session_id}/pr/review-feedback"
    await api.http.post(url, json={"ids": ["T1:C1", "PRR_1"]})
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "review_ready", 2)

    pushed = await approve(api, session_id)

    assert pushed.status_code == 200, pushed.text
    sha = pushed.json()["commit_sha"]
    # Only the thread that went to the agent; a review's own text gets no reply.
    assert replies(api) == [
        ("-f", "thread=T1", "-f", f"body=Addressed in {sha[:7]} (sent by Nest)"),
    ]
    assert (await session_of(api, session_id))["review"]["replied"] == ["T1:C1"]

    await edited(api, session_id, "Again.", 3)
    again = await approve(api, session_id)

    assert again.status_code == 200, again.text
    assert len(replies(api)) == 1


async def test_a_push_that_opens_the_pull_request_replies_nowhere(api: Api) -> None:
    session_id = await finished_with_changes(api)
    store = SessionStore(api.ctx.db, api.ctx.clock)
    item = parse_reviews(review_threads([thread("T1", ("C1", "sam", "x"))], [])).items[0]
    await store.set_review(
        session_id, PrReview(items=[item], sent=[item.id], changes_requested=False)
    )

    opened_now = await approve(api, session_id)

    assert opened_now.status_code == 200
    assert replies(api) == []


async def test_a_reply_that_fails_does_not_fail_the_push_and_is_tried_again(
    api: Api, caplog: pytest.LogCaptureFixture
) -> None:
    session_id = await reviewed(api, review_threads([thread("T1", ("C1", "sam", "x"))], []))
    api.provider.script(edit({"fix.txt": "done\n"}, reply("Done.")))
    await api.http.post(f"/api/sessions/{session_id}/pr/review-feedback")
    await reach(api, session_id, "idle", results=2)
    await notified(api, session_id, "review_ready", 2)
    api.runner.failures["gh api graphql"] = CommandError(["gh"], 1, "GraphQL: secret detail")

    with caplog.at_level(logging.WARNING):
        pushed = await approve(api, session_id)

    assert pushed.status_code == 200, pushed.text
    assert (await session_of(api, session_id))["review"]["replied"] == []
    assert "could not reply on a review thread of" in caplog.text
    assert "secret" not in caplog.text

    await edited(api, session_id, "Again.", 3)
    await approve(api, session_id)

    assert len(replies(api)) == 2
    assert (await session_of(api, session_id))["review"]["replied"] == ["T1:C1"]
