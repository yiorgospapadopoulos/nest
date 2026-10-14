import asyncio
import logging
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from nestd.approvals.models import Approval, ApprovalKind, ApprovalStatus
from nestd.approvals.queue import ApprovalQueue
from nestd.approvals.store import ApprovalStore
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError
from nestd.notifications.notifier import Notifier
from nestd.prs.errors import PrReadError
from nestd.prs.monitor import FAST, SLOW, SLOW_AFTER, PrMonitor
from nestd.sessions.models import Session
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_runner import PR_URL, FakeRunner, check_run, pr_json
from tests.fakes import FakeClock
from tests.test_session_store import new_session

PENDING = [check_run("unit", status="IN_PROGRESS", conclusion="")]
PASSED = [check_run("unit"), check_run("lint")]
FAILED = [check_run("unit", conclusion="FAILURE"), check_run("lint")]


class Env:
    def __init__(self, db: Database, clock: FakeClock, tmp_path: Path) -> None:
        self.clock = clock
        self.bus = EventBus(db, clock)
        self.store = SessionStore(db, clock)
        self.approvals = ApprovalQueue(ApprovalStore(db, clock), self.bus, Notifier(self.bus))
        self.runner = FakeRunner()
        self.monitor = PrMonitor(
            store=self.store,
            bus=self.bus,
            approvals=self.approvals,
            notifier=Notifier(self.bus),
            run=self.runner,
            clock=clock,
            cwd=tmp_path,
            tick=timedelta(milliseconds=10),
        )

    async def session(self, pr_url: str | None = PR_URL) -> Session:
        session = await self.store.create(new_session())
        return await self.store.update(session.id, pr_url=pr_url)

    async def events(self, session_id: str, event_type: str) -> list[dict[str, JsonValue]]:
        events = await self.bus.session_events(session_id)
        return [e.payload for e in events if e.type == event_type]

    async def notices(self, session_id: str, kind: str) -> list[str]:
        payloads = await self.events(session_id, types.NOTIFY)
        return [str(p["text"]) for p in payloads if p["kind"] == kind]

    async def merges(self, session_id: str) -> list[Approval]:
        items = await self.approvals.list_approvals()
        return [a for a in items if a.session_id == session_id and a.kind is ApprovalKind.MERGE]

    def views(self) -> int:
        return len(self.runner.gh_calls("view"))


@pytest.fixture
def env(db: Database, clock: FakeClock, tmp_path: Path) -> Env:
    return Env(db, clock, tmp_path)


async def test_a_new_pull_request_is_read_and_published_without_reordering(env: Env) -> None:
    session = await env.session()
    env.clock.advance(timedelta(minutes=1))
    env.runner.pr_view = pr_json(statusCheckRollup=PENDING)

    await env.monitor.tick()

    stored = await env.store.get(session.id)
    assert stored.pr is not None
    assert (stored.pr.state, stored.pr.checks.state) == ("open", "pending")
    assert stored.pr.updated_at == env.clock.now()
    # A status is not the user's or the agent's work, so the chat list order stays.
    assert stored.updated_at == session.updated_at
    (published,) = await env.events(session.id, types.SESSION_PR)
    assert published == {"pr": stored.pr.model_dump(mode="json")}
    assert env.runner.calls[0][:4] == ("gh", "pr", "view", PR_URL)


async def test_sessions_without_a_pull_request_are_not_read(env: Env) -> None:
    await env.session(pr_url=None)

    await env.monitor.tick()

    assert env.runner.calls == []


async def test_reads_every_minute_then_every_five_once_nothing_changed_for_an_hour(
    env: Env,
) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json(statusCheckRollup=PENDING)
    await env.monitor.tick()
    first = (await env.store.get(session.id)).pr
    assert first is not None

    env.clock.advance(FAST - timedelta(seconds=1))
    await env.monitor.tick()
    assert env.views() == 1
    env.clock.advance(timedelta(seconds=1))
    await env.monitor.tick()
    assert env.views() == 2

    # Unchanged: nothing published, and the change time stays.
    unchanged = (await env.store.get(session.id)).pr
    assert unchanged is not None
    assert unchanged.changed_at == first.changed_at
    assert unchanged.updated_at == env.clock.now()
    assert len(await env.events(session.id, types.SESSION_PR)) == 1

    env.clock.advance(SLOW_AFTER)
    await env.monitor.tick()
    assert env.views() == 3
    env.clock.advance(SLOW - timedelta(seconds=1))
    await env.monitor.tick()
    assert env.views() == 3
    env.clock.advance(timedelta(seconds=1))
    await env.monitor.tick()
    assert env.views() == 4

    # A change (new commits) brings back the one minute interval.
    env.runner.pr_view = pr_json(statusCheckRollup=PENDING, headRefOid="def456")
    env.clock.advance(SLOW)
    await env.monitor.tick()
    env.clock.advance(FAST)
    await env.monitor.tick()
    assert env.views() == 6


@pytest.mark.parametrize("state", ["MERGED", "CLOSED"])
async def test_merged_and_closed_pull_requests_are_no_longer_read(env: Env, state: str) -> None:
    await env.session()
    env.runner.pr_view = pr_json(state=state)

    await env.monitor.tick()
    env.clock.advance(SLOW)
    await env.monitor.tick()

    assert env.views() == 1


async def test_a_failed_read_is_logged_and_waits_for_the_interval(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    session = await env.session()

    with caplog.at_level(logging.WARNING):
        await env.monitor.tick()
        await env.monitor.tick()

    assert env.views() == 1
    assert (await env.store.get(session.id)).pr is None
    assert f"could not read pull request {PR_URL} (CommandError)" in caplog.text
    # gh's output is never logged.
    assert "could not reach GitHub" not in caplog.text
    env.clock.advance(FAST)
    await env.monitor.tick()
    assert env.views() == 2


@pytest.mark.parametrize(
    ("failure", "detail"),
    [
        (CommandError(["gh"], 4, "gh auth login required\n"), "gh auth login required"),
        (FileNotFoundError("No such file: 'gh'"), "No such file: 'gh'"),
    ],
)
async def test_refresh_raises_read_errors(env: Env, failure: Exception, detail: str) -> None:
    session = await env.session()
    env.runner.failures["gh pr view"] = failure

    with pytest.raises(PrReadError, match=detail) as raised:
        await env.monitor.refresh(session)

    assert raised.value.status_code == 502


async def test_garbled_gh_output_is_a_read_error(env: Env) -> None:
    session = await env.session()
    env.runner.pr_view = "{}"

    with pytest.raises(PrReadError, match="could not read pull request"):
        await env.monitor.refresh(session)


async def test_refresh_without_a_pull_request_does_nothing(env: Env) -> None:
    session = await env.session(pr_url=None)

    assert await env.monitor.refresh(session) == session
    assert env.runner.calls == []


async def test_failing_checks_notify_once_per_commit(env: Env) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json(statusCheckRollup=FAILED)

    await env.monitor.tick()
    env.runner.pr_view = pr_json(statusCheckRollup=FAILED, reviewDecision="APPROVED")
    env.clock.advance(FAST)
    await env.monitor.tick()

    assert await env.notices(session.id, "ci_failed") == ["CI failed: unit"]

    # The agent pushed a fix that fails again.
    env.runner.pr_view = pr_json(statusCheckRollup=FAILED, headRefOid="def456")
    env.clock.advance(FAST)
    await env.monitor.tick()
    assert len(await env.notices(session.id, "ci_failed")) == 2
    assert await env.merges(session.id) == []


async def test_many_failing_checks_are_shortened(env: Env) -> None:
    session = await env.session()
    names = [f"job{i}" for i in range(7)]
    env.runner.pr_view = pr_json(
        statusCheckRollup=[check_run(name, conclusion="FAILURE") for name in names]
    )

    await env.monitor.tick()

    assert await env.notices(session.id, "ci_failed") == [
        "CI failed: job0, job1, job2, job3, job4 and 2 more"
    ]


async def test_passing_checks_create_one_merge_approval(env: Env) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json(statusCheckRollup=PENDING)
    await env.monitor.tick()
    assert await env.merges(session.id) == []

    env.runner.pr_view = pr_json(statusCheckRollup=PASSED)
    env.clock.advance(FAST)
    await env.monitor.tick()
    # Other changes while it stays ready add nothing.
    env.runner.pr_view = pr_json(statusCheckRollup=PASSED, reviewDecision="APPROVED")
    env.clock.advance(FAST)
    await env.monitor.tick()

    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.PENDING
    assert merge.payload == {
        "number": 7,
        "title": "Do it",
        "url": PR_URL,
        "head_sha": "abc123",
        "checks": {"state": "success", "passed": 2, "failed": 0, "pending": 0},
    }
    assert await env.notices(session.id, "ready_to_merge") == ["#7 passed 2 checks; ready to merge"]


@pytest.mark.parametrize(
    ("rollup", "text"),
    [
        ([], "#7 has no checks; ready to merge"),
        ([check_run("ci")], "#7 passed 1 check; ready to merge"),
    ],
)
async def test_the_merge_notice_names_the_checks(env: Env, rollup: list[object], text: str) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json(statusCheckRollup=rollup)

    await env.monitor.tick()

    assert await env.notices(session.id, "ready_to_merge") == [text]


async def test_a_merge_approval_expires_when_the_pull_request_is_blocked_again(env: Env) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json(statusCheckRollup=PASSED)
    await env.monitor.tick()

    # GitHub recomputing mergeability is no reason to drop the approval.
    env.runner.pr_view = pr_json(statusCheckRollup=PASSED, mergeable="UNKNOWN")
    env.clock.advance(FAST)
    await env.monitor.tick()
    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.PENDING

    # New commits start the checks again.
    env.runner.pr_view = pr_json(statusCheckRollup=PENDING, headRefOid="def456")
    env.clock.advance(FAST)
    await env.monitor.tick()
    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.EXPIRED
    assert merge.resolution == {"reason": "the pull request is not ready to merge any more"}

    env.runner.pr_view = pr_json(statusCheckRollup=PASSED, headRefOid="def456")
    env.clock.advance(FAST)
    await env.monitor.tick()
    statuses = [m.status for m in await env.merges(session.id)]
    assert statuses == [ApprovalStatus.EXPIRED, ApprovalStatus.PENDING]


async def test_a_pull_request_merged_on_github_expires_the_merge_approval(env: Env) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json()
    await env.monitor.tick()

    env.runner.pr_view = pr_json(state="MERGED")
    env.clock.advance(FAST)
    await env.monitor.tick()

    (merge,) = await env.merges(session.id)
    assert merge.status is ApprovalStatus.EXPIRED
    assert merge.resolution == {"reason": "the pull request was merged"}


async def test_a_dismissed_merge_approval_is_not_created_again_while_nothing_changes(
    env: Env,
) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json()
    await env.monitor.tick()
    (merge,) = await env.merges(session.id)
    await env.approvals.resolve(merge.id, {"dismissed": True})

    env.runner.pr_view = pr_json(reviewDecision="APPROVED")
    env.clock.advance(FAST)
    await env.monitor.tick()

    assert len(await env.merges(session.id)) == 1


async def test_check_soon_reads_at_once_and_wakes_the_loop(env: Env) -> None:
    session = await env.session()
    env.runner.pr_view = pr_json(statusCheckRollup=PENDING)
    await env.monitor.tick()

    await env.monitor.start()
    try:
        env.monitor.check_soon(session.id)
        await until(lambda: env.views() == 2)
        await asyncio.sleep(0.05)
        # Read once; afterwards it waits for its interval again.
        assert env.views() == 2
    finally:
        await env.monitor.stop()
    await env.monitor.stop()


async def test_the_loop_logs_unexpected_failures_and_goes_on(
    env: Env, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[int] = []

    async def broken() -> None:
        calls.append(1)
        msg = "boom"
        raise RuntimeError(msg)

    monkeypatch.setattr(env.monitor, "tick", broken)
    with caplog.at_level(logging.WARNING):
        await env.monitor.start()
        await until(lambda: len(calls) >= 2)
        await env.monitor.stop()

    assert "pull request check failed (RuntimeError)" in caplog.text
