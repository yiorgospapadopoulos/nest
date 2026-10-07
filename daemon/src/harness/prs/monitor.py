"""Follows the pull requests harness opened: checks, mergeability and state (D034).

Each open pull request is read with `gh pr view` every minute, and every five minutes once
nothing changed for an hour; merged and closed ones are no longer read. A change is stored
on the session and published as `session.pr`. Failing checks notify; a pull request whose
checks passed and that GitHub can merge becomes a merge approval.
"""

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from harness.approvals.models import ApprovalKind
from harness.approvals.queue import ApprovalQueue
from harness.clock import Clock
from harness.events import types
from harness.events.bus import EventBus
from harness.gitops.runner import CommandError, CommandRunner
from harness.notifications.notifier import Notifier
from harness.prs.errors import PrReadError
from harness.prs.github import fetch_status
from harness.prs.models import PrStatus
from harness.sessions.models import Session
from harness.sessions.store import SessionStore

logger = logging.getLogger(__name__)

# How often the schedule is checked; each pull request still waits for its interval.
TICK = timedelta(seconds=15)
FAST = timedelta(seconds=60)
SLOW = timedelta(minutes=5)
# Without a change for this long, a pull request is read at the SLOW interval.
SLOW_AFTER = timedelta(hours=1)
MAX_FAILING_NAMES = 5


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
        tick: timedelta = TICK,
    ) -> None:
        """`run` runs gh with the user's login; `cwd` is a folder outside any repository."""
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
        return await self.record(session, status)

    async def record(self, session: Session, status: PrStatus) -> Session:
        """Store a status; when it changed, publish it and react to the change."""
        old = session.pr
        if old is not None and old.same_as(status):
            return await self._store.set_pr(
                session.id, status.model_copy(update={"changed_at": old.changed_at})
            )
        session = await self._store.set_pr(session.id, status)
        await self._bus.publish(
            types.SESSION_PR, {"pr": status.model_dump(mode="json")}, session.id
        )
        await self._react(session, old, status)
        return session

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

    async def _react(self, session: Session, old: PrStatus | None, new: PrStatus) -> None:
        if new.blocked():
            await self._approvals.expire(session.id, (ApprovalKind.MERGE,), _block_reason(new))
        if new.checks.state == "failure" and (
            old is None or old.checks.state != "failure" or old.head_sha != new.head_sha
        ):
            names = new.failing_checks()
            shown = ", ".join(names[:MAX_FAILING_NAMES])
            more = len(names) - MAX_FAILING_NAMES
            text = f"CI failed: {shown}" + (f" and {more} more" if more > 0 else "")
            await self._notifier.notify("ci_failed", session.id, session.repo, session.title, text)
        was_ready = old is not None and old.ready_to_merge() and old.head_sha == new.head_sha
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


def _checks_text(pr: PrStatus) -> str:
    passed = pr.checks.passed
    if not passed:
        return "has no checks"
    return "passed 1 check" if passed == 1 else f"passed {passed} checks"


def _block_reason(pr: PrStatus) -> str:
    if pr.state != "open":
        return f"the pull request was {pr.state}"
    return "the pull request is not ready to merge any more"
