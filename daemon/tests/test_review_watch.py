from pathlib import Path

import pytest

from harness.approvals.queue import ApprovalQueue
from harness.approvals.store import ApprovalStore
from harness.events.bus import EventBus
from harness.notifications.notifier import Notifier
from harness.review import watch
from harness.review.models import SessionDiff
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


async def test_an_unexpected_diff_error_is_logged_and_gets_no_review(
    tmp_path: Path,
    db: Database,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """BUG-01: the turn's "finished" notice still goes out (it follows a None)."""

    async def broken(cwd: Path, base: str | None) -> SessionDiff:
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr(watch, "session_diff", broken)
    bus = EventBus(db, clock)
    queue = ApprovalQueue(ApprovalStore(db, clock), bus, Notifier(bus))
    watcher = ReviewWatcher(queue, Tracking(bus))
    session = await SessionStore(db, clock).create(new_session(cwd=tmp_path, base_ref="abc"))

    assert await watcher.turn_ended(session) is None
    assert await queue.list_approvals() == []
    assert f"could not diff session {session.id} for review" in caplog.text
