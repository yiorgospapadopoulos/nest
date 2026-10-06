from pathlib import Path

from harness.approvals.queue import ApprovalQueue
from harness.approvals.store import ApprovalStore
from harness.events.bus import EventBus
from harness.notifications.notifier import Notifier
from harness.review.watch import ReviewWatcher
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from harness.tracking.service import Tracking
from tests.fakes import FakeClock
from tests.test_session_store import new_session


async def test_a_working_directory_git_cannot_diff_gets_no_review(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    bus = EventBus(db, clock)
    queue = ApprovalQueue(ApprovalStore(db, clock), bus, Notifier(bus))
    watcher = ReviewWatcher(queue, Tracking(bus))
    session = await SessionStore(db, clock).create(new_session(cwd=tmp_path, base_ref="abc"))

    assert await watcher.turn_ended(session) is None
    assert await queue.list_approvals() == []
