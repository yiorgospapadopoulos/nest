"""Follows the pull requests Nest opened: checks, mergeability and state (D034).

Each open pull request is read with `gh pr view` every minute, and every five minutes once
nothing changed for an hour; merged and closed ones are no longer read. A change is stored
on the session and published as `session.pr`. Failing checks notify; a pull request whose
checks passed and that GitHub can merge becomes a merge approval.

An open pull request's review comments are read with it (B101), kept on the session and
published as `session.pr_review`. New ones wait in Needs you as a review comments
approval, or with the session's auto send go to the agent at once.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path
from weakref import WeakValueDictionary

from pydantic import JsonValue, ValidationError

from nestd.approvals.models import ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.clock import Clock
from nestd.errors import NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.gitops.runner import CommandError, CommandRunner
from nestd.notifications.notifier import Notifier
from nestd.prs.errors import NoReviewCommentsError, PrReadError
from nestd.prs.github import fetch_status, pr_number
from nestd.prs.models import PrReview, PrStatus
from nestd.prs.review_feedback import feedback_message
from nestd.prs.reviews import ReviewRead, fetch_reviews, parse_reviews, reply_to_thread
from nestd.sessions.models import Sender, SendResult, Session, SessionState
from nestd.sessions.store import SessionStore

logger = logging.getLogger(__name__)

# How often the schedule is checked; each pull request still waits for its interval.
TICK = timedelta(seconds=15)
FAST = timedelta(seconds=60)
SLOW = timedelta(minutes=5)
# Without a change for this long, a pull request is read at the SLOW interval.
SLOW_AFTER = timedelta(hours=1)
MAX_FAILING_NAMES = 5

# Sends a message to a session's agent, as the user's messages go (B101).
type SendMessage = Callable[[str, str, Sender], Awaitable[SendResult]]


class PrMonitor:
    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        approvals: ApprovalQueue,
        notifier: Notifier,
        run: CommandRunner,
        clock: Clock,
        cwd: Path,
        send: SendMessage,
        tick: timedelta = TICK,
    ) -> None:
        """`run` runs gh with the user's login; `cwd` is a folder outside any repository;
        `send` gives the agent its pull request's review comments.
        """
        self._send = send
        # One send of review comments per session at a time, so none goes twice.
        self._sending: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()
        self._store = store
        self._bus = bus
        self._approvals = approvals
        self._notifier = notifier
        self._run = run
        self._clock = clock
        self._cwd = cwd
        self._tick = tick
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        # Failed reads wait for the next interval too, so a broken gh is not run every tick.
        self._attempts: dict[str, datetime] = {}
        # Sessions to read at the next check whatever their interval, such as after a push.
        self._soon: set[str] = set()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    def check_soon(self, session_id: str) -> None:
        """Read the session's pull request at the next check, for example after a push."""
        self._soon.add(session_id)
        self._wake.set()

    async def tick(self) -> None:
        """Read every open pull request whose interval has passed."""
        now = self._clock.now()
        for session in await self._store.with_prs():
            if self._due(session, now):
                with suppress(PrReadError):
                    await self.refresh(session)

    async def refresh(self, session: Session) -> Session:
        """Read the session's pull request now; raises PrReadError when gh fails."""
        url = session.pr_url
        if url is None:
            return session
        now = self._clock.now()
        self._attempts[session.id] = now
        self._soon.discard(session.id)
        try:
            status = await fetch_status(self._run, url, self._cwd, now)
        except (CommandError, OSError, ValidationError) as error:
            # gh output can quote anything, so only the kind of failure is logged.
            logger.warning("could not read pull request %s (%s)", url, type(error).__name__)
            raise PrReadError(url, error) from None
        # Review comments first, so a new one never lets a merge approval show (B101).
        was_held = _held(session)
        read = await self._read_reviews(url) if status.state == "open" else None
        session = await self._review(session, status, read)
        return await self.record(session, status, was_held)

    async def record(
        self, session: Session, status: PrStatus, was_held: bool | None = None
    ) -> Session:
        """Store a status; when it changed, publish it and react to the change.
        `was_held`: whether review comments kept the merge away before this read (None:
        as they do now).
        """
        old = session.pr
        held = _held(session) if was_held is None else was_held
        if old is not None and old.same_as(status):
            session = await self._store.set_pr(
                session.id, status.model_copy(update={"changed_at": old.changed_at})
            )
            await self._merge(session, old, status, held)
            return session
        session = await self._store.set_pr(session.id, status)
        await self._bus.publish(
            types.SESSION_PR, {"pr": status.model_dump(mode="json")}, session.id
        )
        await self._react(session, old, status, held)
        return session

    async def set_review(self, session_id: str, review: PrReview) -> Session:
        """Store the review comments and publish them."""
        session = await self._store.set_review(session_id, review)
        await self._bus.publish(
            types.SESSION_PR_REVIEW, {"review": review.model_dump(mode="json")}, session_id
        )
        return session

    async def send_review(self, session_id: str, ids: list[str] | None = None) -> SendResult:
        """Send the review comments that wait (only those in `ids`, when given) to the
        agent as a message, which starts a turn or is queued like any other, and mark them
        sent; raises NoReviewCommentsError when none of them waits. Those left, or cut from
        a long message, wait in a new approval.
        """
        async with self._lock(session_id):
            return await self._send_review(await self._store.get(session_id), ids)

    async def set_auto_send(self, session_id: str, auto_send: bool) -> Session:
        """Whether new review comments go to the agent on their own."""
        async with self._lock(session_id):
            session = await self._store.get(session_id)
            review = session.review or PrReview(items=[], sent=[], changes_requested=False)
            return await self.set_review(
                session_id, review.model_copy(update={"auto_send": auto_send})
            )

    async def reply_addressed(self, session_id: str, sha: str) -> None:
        """After a push of commit `sha` to the session's pull request, reply once on each
        thread whose comments went to the agent. A failed reply is only logged and is
        tried again after the next push.
        """
        async with self._lock(session_id):
            session = await self._store.get(session_id)
            review = session.review
            if review is None:
                return
            replied = list(review.replied)
            body = f"Addressed in {sha[:7]} (sent by Nest)"
            for item in review.items:
                if item.kind != "thread" or item.id not in review.sent or item.id in replied:
                    continue
                thread_id = item.id.split(":", 1)[0]
                try:
                    await reply_to_thread(self._run, self._cwd, thread_id, body)
                except (CommandError, OSError) as error:
                    logger.warning(
                        "could not reply on a review thread of %s (%s)",
                        session_id,
                        type(error).__name__,
                    )
                    continue
                replied.append(item.id)
            if replied != review.replied:
                await self.set_review(session_id, review.model_copy(update={"replied": replied}))

    def _lock(self, session_id: str) -> asyncio.Lock:
        """Held while a session's review comments change, so none goes twice or is lost."""
        return self._sending.setdefault(session_id, asyncio.Lock())

    async def _send_review(self, session: Session, ids: list[str] | None = None) -> SendResult:
        review = session.review
        pending = [] if review is None else review.pending()
        if ids is not None:
            chosen = set(ids)
            pending = [item for item in pending if item.id in chosen]
        if review is None or session.pr_url is None or not pending:
            raise NoReviewCommentsError
        number = pr_number(session.pr_url)
        text, sent = feedback_message(number, pending)
        comments: list[JsonValue] = [item.model_dump(mode="json") for item in sent]
        extra: dict[str, JsonValue] = {
            "review_feedback": {"number": number, "count": len(sent), "comments": comments}
        }
        result = await self._send(session.id, text, Sender(extra=extra))
        was_held = _held(session)
        review = review.model_copy(update={"sent": [*review.sent, *(i.id for i in sent)]})
        session = await self.set_review(session.id, review)
        if session.pr is not None:
            # A review's text once sent no longer keeps the merge away.
            await self._merge(session, session.pr, session.pr, was_held)
        if review.pending() and not review.auto_send:
            # The rest wait in a new approval, which replaces this one.
            await self._ask(session, review, None)
            return result
        ask = await self._approvals.pending(session.id, ApprovalKind.REVIEW_COMMENTS)
        if ask is not None:
            await self._approvals.resolve(ask.id, {"action": "sent"})
        return result

    async def _read_reviews(self, url: str) -> ReviewRead | None:
        """The review comments; None when they cannot be read, which is only logged."""
        try:
            return parse_reviews(await fetch_reviews(self._run, url, self._cwd))
        except (CommandError, OSError, ValidationError) as error:
            logger.warning("could not read the reviews of %s (%s)", url, type(error).__name__)
            return None

    async def _review(self, session: Session, status: PrStatus, read: ReviewRead | None) -> Session:
        if status.state != "open":
            await self._approvals.expire(
                session.id, (ApprovalKind.REVIEW_COMMENTS,), _block_reason(status)
            )
            return session
        if read is None:
            return session
        async with self._lock(session.id):
            # Read again: comments may have been sent meanwhile.
            session = await self._store.get(session.id)
            old = session.review
            review = PrReview(
                items=read.items,
                sent=[] if old is None else old.sent,
                changes_requested=read.changes_requested
                or status.review_decision == "changes_requested",
                auto_send=old is not None and old.auto_send,
                replied=[] if old is None else old.replied,
            )
            if review != old:
                session = await self.set_review(session.id, review)
            if review.auto_send and review.pending():
                try:
                    await self._send_review(session)
                    return await self._store.get(session.id)
                except NestError as error:
                    # Such as a chat that was closed: they wait in Needs you instead.
                    logger.warning(
                        "could not send review comments to %s (%s)",
                        session.id,
                        type(error).__name__,
                    )
            before = None if old is None else [item.id for item in old.pending()]
            await self._ask(session, review, before)
            return session

    async def _ask(self, session: Session, review: PrReview, before: list[str] | None) -> None:
        """Ask the user about the comments that wait, unless they waited `before` too;
        none waiting ends the ask.
        """
        pending = review.pending()
        if not pending:
            await self._approvals.expire(
                session.id, (ApprovalKind.REVIEW_COMMENTS,), "no review comments wait any more"
            )
            return
        if [item.id for item in pending] == before or session.state is SessionState.CLOSED:
            return
        assert session.pr_url is not None  # noqa: S101 (only sessions with a pull request)
        number = pr_number(session.pr_url)
        count = "1 review comment" if len(pending) == 1 else f"{len(pending)} review comments"
        await self._approvals.add(
            session.id,
            ApprovalKind.REVIEW_COMMENTS,
            {
                "number": number,
                "url": session.pr_url,
                "changes_requested": review.changes_requested,
                "comments": [item.model_dump(mode="json") for item in pending],
            },
            f"{count} on #{number}",
        )

    def _due(self, session: Session, now: datetime) -> bool:
        pr = session.pr
        if pr is not None and pr.state != "open":
            return False
        if session.id in self._soon:
            return True
        moments = [self._attempts.get(session.id), None if pr is None else pr.updated_at]
        last = max((moment for moment in moments if moment is not None), default=None)
        if last is None:
            return True
        quiet = pr is not None and now - pr.changed_at >= SLOW_AFTER
        return now - last >= (SLOW if quiet else FAST)

    async def _react(
        self, session: Session, old: PrStatus | None, new: PrStatus, was_held: bool
    ) -> None:
        if new.checks.state == "failure" and (
            old is None or old.checks.state != "failure" or old.head_sha != new.head_sha
        ):
            names = new.failing_checks()
            shown = ", ".join(names[:MAX_FAILING_NAMES])
            more = len(names) - MAX_FAILING_NAMES
            text = f"CI failed: {shown}" + (f" and {more} more" if more > 0 else "")
            await self._notifier.notify("ci_failed", session.id, session.repo, session.title, text)
        await self._merge(session, old, new, was_held)

    async def _merge(
        self, session: Session, old: PrStatus | None, new: PrStatus, was_held: bool
    ) -> None:
        """Expire the merge approval when the pull request is blocked or review comments
        are open; add it when it became ready to merge, or the comments cleared.
        """
        held = _held(session)
        if new.blocked():
            await self._approvals.expire(session.id, (ApprovalKind.MERGE,), _block_reason(new))
        if held:
            await self._approvals.expire(
                session.id, (ApprovalKind.MERGE,), "review comments are open on the pull request"
            )
            return
        was_ready = (
            old is not None
            and old.ready_to_merge()
            and old.head_sha == new.head_sha
            and not was_held
        )
        if new.ready_to_merge() and not was_ready:
            await self._approvals.add(
                session.id,
                ApprovalKind.MERGE,
                {
                    "number": new.number,
                    "title": new.title,
                    "url": new.url,
                    "head_sha": new.head_sha,
                    "checks": new.checks.model_dump(mode="json", exclude={"items"}),
                },
                f"#{new.number} {_checks_text(new)}; ready to merge",
            )

    async def _loop(self) -> None:
        while True:
            with suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), self._tick.total_seconds())
            self._wake.clear()
            try:
                await self.tick()
            except Exception as error:
                logger.warning("pull request check failed (%s)", type(error).__name__)


def _held(session: Session) -> bool:
    """Whether review comments keep the merge approval away (B101)."""
    return session.review is not None and session.review.blocks_merge()


def _checks_text(pr: PrStatus) -> str:
    passed = pr.checks.passed
    if not passed:
        return "has no checks"
    return "passed 1 check" if passed == 1 else f"passed {passed} checks"


def _block_reason(pr: PrStatus) -> str:
    if pr.state != "open":
        return f"the pull request was {pr.state}"
    return "the pull request is not ready to merge any more"
