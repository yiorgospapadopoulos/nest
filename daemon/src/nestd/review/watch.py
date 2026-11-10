"""A turn that changes the work in the working tree puts the work up for review (B56); the
review covers what is not committed (B58), so a turn that commits it all withdraws it.

The watcher notes the work's fingerprint when a run of turns starts and compares it at the
turn's end, so a turn that only talks leaves the pending review as it is. The start is
kept in memory only: after a restart mid-turn the turn's end reviews the work as it is.

Work can also be committed while the chat is idle, from a terminal, an editor or another
chat. The project's branches moving says so (B96), and the pending reviews of its idle
chats are checked again then: one with nothing left goes (B160).
"""

import logging

from pydantic import JsonValue

from nestd.approvals.models import Approval, ApprovalKind, ApprovalStatus
from nestd.approvals.queue import ApprovalQueue
from nestd.review.diffs import session_diff
from nestd.review.models import SessionDiff
from nestd.review.scope import ReviewScope
from nestd.sessions.models import Session
from nestd.sessions.rules import require_cwd
from nestd.tracking.service import Tracking

logger = logging.getLogger(__name__)


class ReviewWatcher:
    def __init__(self, approvals: ApprovalQueue, tracking: Tracking, scope: ReviewScope) -> None:
        self._approvals = approvals
        self._tracking = tracking
        self._scope = scope
        # Session id to the work's fingerprint when its turns started.
        self._starts: dict[str, str] = {}

    def has_start(self, session_id: str) -> bool:
        return session_id in self._starts

    async def turn_started(self, session: Session) -> None:
        """Note the work as the turn starts; queued turns that follow without an idle in
        between are one run, so an existing start is kept.
        """
        if self.has_start(session.id):
            return
        diff = await self._diff(session)
        if diff is not None:
            self._starts[session.id] = diff.fingerprint

    async def turn_ended(self, session: Session) -> Approval | None:
        """Create a review of the session's work, replacing a pending one, when the turn
        changed it. None when it did not: no work left (a pending review is withdrawn), the
        work as it was when the turn started (a pending review stays), or no diff.
        """
        start = self._starts.pop(session.id, None)
        diff = await self._diff(session)
        if diff is None:
            return None
        if not diff.files:
            await self._approvals.supersede(session.id, ApprovalKind.REVIEW)
            return None
        if diff.fingerprint == start:
            return None
        return await self._review(session, diff)

    async def reviewed_in(self, repo: str) -> list[str]:
        """The sessions of the project with a pending review."""
        pending = await self._approvals.list_approvals(ApprovalStatus.PENDING, repo)
        return list(dict.fromkeys(a.session_id for a in pending if a.kind is ApprovalKind.REVIEW))

    async def recheck(self, session: Session) -> None:
        """Commits were made while the chat was idle: a pending review with no work left
        goes, one whose files or counts changed is made again, any other stays as it is.
        """
        pending = await self._approvals.pending(session.id, ApprovalKind.REVIEW)
        if pending is None:
            return
        diff = await self._diff(session)
        if diff is None:
            return
        if not diff.files:
            await self._approvals.supersede(session.id, ApprovalKind.REVIEW)
        elif _counts(pending.payload) != _counts(_payload(diff)):
            await self._review(session, diff)

    async def _review(self, session: Session, diff: SessionDiff) -> Approval:
        stats = diff.stats
        return await self._approvals.add(
            session.id,
            ApprovalKind.REVIEW,
            {**_payload(diff), "summary": await self._tracking.summary(session.id)},
            f"{stats.files} files changed, +{stats.additions} -{stats.deletions}",
        )

    async def held(self, session: Session) -> None:
        """Helpers go on after the turn (B133), so the work is not ready: a pending review
        is withdrawn, and without a start the work is reviewed as it is when they end.
        """
        if await self._approvals.supersede(session.id, ApprovalKind.REVIEW):
            self._starts.pop(session.id, None)

    async def refresh(self, session: Session) -> None:
        """The work changed outside a turn (files restored, B59): review it as it is now."""
        self._starts.pop(session.id, None)
        await self.turn_ended(session)

    async def moved(self, session: Session) -> None:
        """The chat works in another folder now (B119): the work is compared with what that
        folder holds, so the project's own changes never pass as this chat's.
        """
        self._starts.pop(session.id, None)
        await self.turn_started(session)

    def forget(self, session_id: str) -> None:
        self._starts.pop(session_id, None)

    async def _diff(self, session: Session) -> SessionDiff | None:
        """The work not committed yet, by Nest or by the agent (B58)."""
        try:
            cwd = require_cwd(session)
            return await session_diff(cwd, only=await self._scope.paths(session, cwd))
        except Exception:
            # Whatever the tree holds, the turn still ends with its "finished" notice.
            logger.exception("could not diff session %s for review", session.id)
            return None


def _payload(diff: SessionDiff) -> dict[str, JsonValue]:
    return {
        "base": diff.base,
        "files": diff.stats.files,
        "additions": diff.stats.additions,
        "deletions": diff.stats.deletions,
        "paths": [f.path for f in diff.files],
    }


def _counts(payload: dict[str, JsonValue]) -> tuple[JsonValue, ...]:
    """What the review card shows of the work, its base aside."""
    return tuple(payload.get(key) for key in ("files", "additions", "deletions", "paths"))
