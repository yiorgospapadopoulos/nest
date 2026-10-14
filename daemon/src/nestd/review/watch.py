"""A turn that ends with changes in the working tree puts the work up for review."""

import logging

from nestd.approvals.models import Approval, ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.review.diffs import session_diff
from nestd.sessions.models import Session
from nestd.sessions.rules import require_cwd
from nestd.tracking.service import Tracking

logger = logging.getLogger(__name__)


class ReviewWatcher:
    def __init__(self, approvals: ApprovalQueue, tracking: Tracking) -> None:
        self._approvals = approvals
        self._tracking = tracking

    async def turn_ended(self, session: Session) -> Approval | None:
        """Create a review of the session's new changes, replacing a pending one; None if
        nothing changed since the session's base, or since the work the user last approved.
        """
        since = session.commit_sha or session.base_ref
        try:
            diff = await session_diff(require_cwd(session), since)
        except Exception:
            # Whatever the tree holds, the turn still ends with its "finished" notice.
            logger.exception("could not diff session %s for review", session.id)
            return None
        if not diff.files:
            return None
        stats = diff.stats
        return await self._approvals.add(
            session.id,
            ApprovalKind.REVIEW,
            {
                "base": since,
                "files": stats.files,
                "additions": stats.additions,
                "deletions": stats.deletions,
                "paths": [f.path for f in diff.files],
                "summary": await self._tracking.summary(session.id),
            },
            f"{stats.files} files changed, +{stats.additions} -{stats.deletions}",
        )
