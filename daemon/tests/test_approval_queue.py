import asyncio
from datetime import timedelta

import pytest
from pydantic import JsonValue

from nestd.approvals.errors import ApprovalNotFoundError, ApprovalNotPendingError
from nestd.approvals.models import Approval, ApprovalKind, ApprovalStatus
from nestd.approvals.queue import ApprovalQueue
from nestd.approvals.store import ApprovalStore
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.notifications.notifier import Notifier
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.async_support import until
from tests.fakes import FakeClock
from tests.test_session_store import new_session

PERMISSION = ApprovalKind.PERMISSION
QUESTION = ApprovalKind.QUESTION
REVIEW = ApprovalKind.REVIEW


class Env:
    def __init__(self, db: Database, clock: FakeClock) -> None:
        self.clock = clock
        self.bus = EventBus(db, clock)
        self.sessions = SessionStore(db, clock)
        self.store = ApprovalStore(db, clock)
        self.queue = ApprovalQueue(self.store, self.bus, Notifier(self.bus))
        self.waiting: list[bool] = []

    def wait(self, session_id: str, kind: ApprovalKind) -> "asyncio.Future[Approval]":
        async def on_waiting(waiting: bool) -> None:
            self.waiting.append(waiting)

        return asyncio.ensure_future(
            self.queue.wait(session_id, kind, {"tool": "Bash"}, "Allow Bash?", on_waiting)
        )

    async def session(self, repo: str = "repo") -> str:
        return (await self.sessions.create(new_session(repo=repo, title=f"{repo} task"))).id

    async def events(self, session_id: str) -> list[tuple[str, dict[str, JsonValue]]]:
        return [(e.type, e.payload) for e in await self.bus.session_events(session_id)]

    async def pending(self, session_id: str) -> Approval:
        await until(lambda: self.queue.waiting(session_id))
        (approval,) = await self.queue.list_approvals(ApprovalStatus.PENDING)
        return approval


@pytest.fixture
def env(db: Database, clock: FakeClock) -> Env:
    return Env(db, clock)


async def test_wait_holds_until_the_item_is_resolved(env: Env) -> None:
    session_id = await env.session()

    waiting = env.wait(session_id, PERMISSION)
    created = await env.pending(session_id)
    assert env.waiting == [True]
    env.clock.advance(timedelta(seconds=3))
    resolved = await env.queue.resolve(created.id, {"behavior": "allow"})

    assert await waiting == resolved
    assert created.kind is PERMISSION
    assert created.status is ApprovalStatus.PENDING
    assert (created.repo, created.title) == ("repo", "repo task")
    assert created.payload == {"tool": "Bash"}
    assert created.resolution is None
    assert created.resolved_at is None
    assert resolved.status is ApprovalStatus.RESOLVED
    assert resolved.resolution == {"behavior": "allow"}
    assert resolved.resolved_at == created.created_at + timedelta(seconds=3)
    assert env.queue.waiting(session_id) is False
    assert env.waiting == [True, False]
    assert await env.events(session_id) == [
        (types.APPROVAL_CREATED, {"approval": created.model_dump(mode="json")}),
        (
            types.NOTIFY,
            {
                "kind": "needs_approval",
                "session_id": session_id,
                "repo": "repo",
                "title": "repo task",
                "text": "Allow Bash?",
            },
        ),
        (types.APPROVAL_RESOLVED, {"approval": resolved.model_dump(mode="json")}),
    ]


async def test_resolving_twice_or_unknown_items_fails(env: Env) -> None:
    session_id = await env.session()
    waiting = env.wait(session_id, QUESTION)
    created = await env.pending(session_id)
    await env.queue.resolve(created.id, {"answers": {}})
    await waiting

    with pytest.raises(ApprovalNotPendingError, match="is resolved"):
        await env.queue.resolve(created.id, {})
    with pytest.raises(ApprovalNotFoundError, match="unknown approval 'nope'"):
        await env.queue.resolve("nope", {})
    with pytest.raises(ApprovalNotFoundError):
        await env.queue.get("nope")
    assert (await env.queue.get(created.id)).status is ApprovalStatus.RESOLVED


async def test_a_cancelled_wait_expires_its_item(env: Env) -> None:
    session_id = await env.session()
    waiting = env.wait(session_id, PERMISSION)
    created = await env.pending(session_id)

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    expired = await env.queue.get(created.id)
    assert expired.status is ApprovalStatus.EXPIRED
    assert expired.resolution == {"reason": "cancelled"}
    assert env.queue.waiting(session_id) is False
    assert env.waiting == [True, False]


async def test_expire_answers_waiters_of_the_given_kinds_only(env: Env) -> None:
    session_id = await env.session()
    other_id = await env.session("other")
    permission = env.wait(session_id, PERMISSION)
    question = env.wait(session_id, QUESTION)
    other = env.wait(other_id, PERMISSION)
    review = await env.queue.add(session_id, REVIEW, {}, "ready")
    await until(lambda: len(env.queue._waiters) == 3)  # pyright: ignore[reportPrivateUsage]

    await env.queue.expire(session_id, (PERMISSION, QUESTION), "interrupted")

    for done in (await permission, await question):
        assert done.status is ApprovalStatus.EXPIRED
        assert done.resolution == {"reason": "interrupted"}
    # Three runs started waiting; the session stopped waiting only after both were answered.
    assert env.waiting == [True, True, True, True, False]
    assert (await env.queue.get(review.id)).status is ApprovalStatus.PENDING
    assert not other.done()
    assert env.queue.waiting(other_id) is True
    await env.queue.expire(other_id, tuple(ApprovalKind), "closed")
    assert (await other).status is ApprovalStatus.EXPIRED


async def test_add_supersedes_the_pending_item_of_the_same_kind(env: Env) -> None:
    session_id = await env.session()
    first = await env.queue.add(session_id, REVIEW, {"n": 1}, "ready")

    second = await env.queue.add(session_id, REVIEW, {"n": 2}, "ready again")

    assert (await env.queue.get(first.id)).status is ApprovalStatus.SUPERSEDED
    assert await env.queue.pending(session_id, REVIEW) == second
    await env.queue.supersede(session_id, REVIEW)
    assert await env.queue.pending(session_id, REVIEW) is None
    notices = [p["kind"] for t, p in await env.events(session_id) if t == types.NOTIFY]
    assert notices == ["review_ready", "review_ready"]


async def test_expire_stale_after_a_restart_keeps_reviews(env: Env) -> None:
    session_id = await env.session()
    # Left pending by the previous process; nothing waits on it any more.
    question = await env.store.create(session_id, QUESTION, {})
    permission = await env.store.create(session_id, PERMISSION, {})
    review = await env.queue.add(session_id, REVIEW, {}, "ready")

    await env.queue.expire_stale()

    stale = await env.queue.get(question.id)
    assert stale.status is ApprovalStatus.EXPIRED
    assert stale.resolution == {"reason": "the daemon restarted"}
    assert (await env.queue.get(permission.id)).status is ApprovalStatus.EXPIRED
    assert (await env.queue.get(review.id)).status is ApprovalStatus.PENDING


async def test_list_filters_by_status_and_repo(env: Env) -> None:
    first = await env.session("alpha")
    second = await env.session("beta")
    a = await env.queue.add(first, REVIEW, {}, "x")
    env.clock.advance(timedelta(seconds=1))
    b = await env.queue.add(second, REVIEW, {}, "x")
    env.clock.advance(timedelta(seconds=1))
    await env.queue.resolve(b.id, {"action": "rejected"})
    c = await env.queue.add(second, REVIEW, {}, "x")

    everything = await env.queue.list_approvals()
    pending = await env.queue.list_approvals(ApprovalStatus.PENDING)
    beta = await env.queue.list_approvals(repo="beta")
    beta_pending = await env.queue.list_approvals(ApprovalStatus.PENDING, "beta")

    assert [x.id for x in everything] == [a.id, b.id, c.id]
    assert [x.id for x in pending] == [a.id, c.id]
    assert [x.id for x in beta] == [b.id, c.id]
    assert [x.id for x in beta_pending] == [c.id]
