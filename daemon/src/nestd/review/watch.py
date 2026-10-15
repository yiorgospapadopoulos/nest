"""A turn that changes the work in the working tree puts the work up for review (B56); the
review covers what is not committed (B58), so a turn that commits it all withdraws it.

The watcher notes the work's fingerprint when a run of turns starts and compares it at the
turn's end, so a turn that only talks leaves the pending review as it is. The start is
kept in memory only: after a restart mid-turn the turn's end reviews the work as it is.
"""

import logging

from nestd.approvals.models import Approval, ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.review.diffs import session_diff
from nestd.review.models import SessionDiff
from nestd.sessions.models import Session
from nestd.sessions.rules import require_cwd
from nestd.tracking.service import Tracking

logger = logging.getLogger(__name__)


class ReviewWatcher:
    def __init__(self, approvals: ApprovalQueue, tracking: Tracking) -> None:
        self._approvals = approvals
        self._tracking = tracking
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
        stats = diff.stats
        return await self._approvals.add(
            session.id,
            ApprovalKind.REVIEW,
            {
                "base": diff.base,
                "files": stats.files,
                "additions": stats.additions,
                "deletions": stats.deletions,
                "paths": [f.path for f in diff.files],
                "summary": await self._tracking.summary(session.id),
            },
            f"{stats.files} files changed, +{stats.additions} -{stats.deletions}",
        )

    def forget(self, session_id: str) -> None:
        self._starts.pop(session_id, None)

    async def _diff(self, session: Session) -> SessionDiff | None:
        """The work not committed yet, by Nest or by the agent (B58)."""
        try:
            return await session_diff(require_cwd(session))
        except Exception:
            # Whatever the tree holds, the turn still ends with its "finished" notice.
            logger.exception("could not diff session %s for review", session.id)
            return None
