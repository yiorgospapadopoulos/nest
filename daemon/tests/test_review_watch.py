from pathlib import Path

import pytest

from nestd.approvals.models import ApprovalStatus
from nestd.approvals.queue import ApprovalQueue
from nestd.approvals.store import ApprovalStore
from nestd.events.bus import EventBus
from nestd.notifications.notifier import Notifier
from nestd.review import watch
from nestd.review.models import SessionDiff
from nestd.review.watch import ReviewWatcher
from nestd.sessions.models import Session
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from nestd.tracking.service import Tracking
from tests.fakes import FakeClock
from tests.git_support import git, init_repo
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

    async def broken(cwd: Path) -> SessionDiff:
        raise IsADirectoryError(21, "Is a directory")

    monkeypatch.setattr(watch, "session_diff", broken)
    bus = EventBus(db, clock)
    queue = ApprovalQueue(ApprovalStore(db, clock), bus, Notifier(bus))
    watcher = ReviewWatcher(queue, Tracking(bus))
    session = await SessionStore(db, clock).create(new_session(cwd=tmp_path, base_ref="abc"))

    assert await watcher.turn_ended(session) is None
    assert await queue.list_approvals() == []
    assert f"could not diff session {session.id} for review" in caplog.text


async def watched(
    tmp_path: Path, db: Database, clock: FakeClock
) -> tuple[ReviewWatcher, ApprovalQueue, Session, Path]:
    """A watcher and a session working in a git repository with an unrelated dirty file."""
    repo = init_repo(tmp_path / "repo")
    (repo / "mine.txt").write_text("the user's\n", encoding="utf-8")
    bus = EventBus(db, clock)
    queue = ApprovalQueue(ApprovalStore(db, clock), bus, Notifier(bus))
    watcher = ReviewWatcher(queue, Tracking(bus))
    base = git(repo, "rev-parse", "HEAD").strip()
    session = await SessionStore(db, clock).create(new_session(cwd=repo, base_ref=base))
    return watcher, queue, session, repo


async def test_a_turn_that_changes_nothing_keeps_the_pending_review(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    watcher, queue, session, _ = await watched(tmp_path, db, clock)
    first = await watcher.turn_ended(session)

    await watcher.turn_started(session)
    again = await watcher.turn_ended(session)

    assert first is not None
    assert again is None
    assert [(a.id, a.status) for a in await queue.list_approvals()] == [
        (first.id, ApprovalStatus.PENDING)
    ]


async def test_a_dirty_tree_the_turn_left_alone_gets_no_review(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    """A "hi" in a chat whose folder already differs from its base is just a chat."""
    watcher, queue, session, _ = await watched(tmp_path, db, clock)

    await watcher.turn_started(session)

    assert await watcher.turn_ended(session) is None
    assert await queue.list_approvals() == []


async def test_a_turn_that_edits_a_file_replaces_the_review(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    watcher, queue, session, repo = await watched(tmp_path, db, clock)
    first = await watcher.turn_ended(session)

    await watcher.turn_started(session)
    (repo / "agent.txt").write_text("agent\n", encoding="utf-8")
    second = await watcher.turn_ended(session)

    assert first is not None
    assert second is not None
    assert second.payload["paths"] == ["agent.txt", "mine.txt"]
    statuses = [(a.id, a.status) for a in await queue.list_approvals()]
    assert statuses == [
        (first.id, ApprovalStatus.SUPERSEDED),
        (second.id, ApprovalStatus.PENDING),
    ]


async def test_a_turn_that_undoes_all_the_work_supersedes_the_review(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    watcher, queue, session, repo = await watched(tmp_path, db, clock)
    first = await watcher.turn_ended(session)

    await watcher.turn_started(session)
    (repo / "mine.txt").unlink()
    ended = await watcher.turn_ended(session)

    assert first is not None
    assert ended is None
    assert [(a.id, a.status) for a in await queue.list_approvals()] == [
        (first.id, ApprovalStatus.SUPERSEDED)
    ]


async def test_a_turn_that_commits_all_the_work_supersedes_the_review(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    """B58: the user asked Claude to commit; nothing is left to review."""
    watcher, queue, session, repo = await watched(tmp_path, db, clock)
    first = await watcher.turn_ended(session)

    await watcher.turn_started(session)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "the agent's commit")
    ended = await watcher.turn_ended(session)

    assert first is not None
    assert ended is None
    assert [(a.id, a.status) for a in await queue.list_approvals()] == [
        (first.id, ApprovalStatus.SUPERSEDED)
    ]


async def test_a_turn_that_commits_part_of_the_work_reviews_the_rest(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    """The review's base is HEAD after the agent's commit, not the session's base (B58)."""
    watcher, queue, session, repo = await watched(tmp_path, db, clock)

    await watcher.turn_started(session)
    git(repo, "add", "mine.txt")
    git(repo, "commit", "-q", "-m", "the agent's commit")
    (repo / "agent.txt").write_text("agent\n", encoding="utf-8")
    review = await watcher.turn_ended(session)

    assert review is not None
    assert review.payload["paths"] == ["agent.txt"]
    assert review.payload["base"] == git(repo, "rev-parse", "HEAD").strip()
    assert review.payload["base"] != session.base_ref
    assert [a.id for a in await queue.list_approvals()] == [review.id]


async def test_without_a_start_the_turn_end_reviews_the_work(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    """The daemon restarted mid-turn, or a turn's start could not be read."""
    watcher, queue, session, _ = await watched(tmp_path, db, clock)
    first = await watcher.turn_ended(session)

    second = await watcher.turn_ended(session)

    assert first is not None
    assert second is not None
    assert [a.status for a in await queue.list_approvals()] == [
        ApprovalStatus.SUPERSEDED,
        ApprovalStatus.PENDING,
    ]


async def test_turns_back_to_back_compare_with_the_first_start(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    """Queued turns run without an idle between them: the first start counts."""
    watcher, queue, session, repo = await watched(tmp_path, db, clock)
    first = await watcher.turn_ended(session)

    await watcher.turn_started(session)
    (repo / "agent.txt").write_text("agent\n", encoding="utf-8")
    assert watcher.has_start(session.id)
    await watcher.turn_started(session)
    second = await watcher.turn_ended(session)

    assert first is not None
    assert second is not None
    assert not watcher.has_start(session.id)
    assert [a.status for a in await queue.list_approvals()] == [
        ApprovalStatus.SUPERSEDED,
        ApprovalStatus.PENDING,
    ]


async def test_a_start_is_used_once(tmp_path: Path, db: Database, clock: FakeClock) -> None:
    watcher, queue, session, _ = await watched(tmp_path, db, clock)
    await watcher.turn_started(session)
    assert await watcher.turn_ended(session) is None

    # No start this time: the work is reviewed as it is.
    assert await watcher.turn_ended(session) is not None
    assert len(await queue.list_approvals()) == 1


async def test_a_forgotten_start_no_longer_counts(
    tmp_path: Path, db: Database, clock: FakeClock
) -> None:
    watcher, _, session, _ = await watched(tmp_path, db, clock)
    await watcher.turn_started(session)

    watcher.forget(session.id)
    watcher.forget(session.id)

    assert not watcher.has_start(session.id)
    assert await watcher.turn_ended(session) is not None


async def test_a_start_git_cannot_diff_is_logged_and_skipped(
    tmp_path: Path, db: Database, clock: FakeClock, caplog: pytest.LogCaptureFixture
) -> None:
    bus = EventBus(db, clock)
    queue = ApprovalQueue(ApprovalStore(db, clock), bus, Notifier(bus))
    watcher = ReviewWatcher(queue, Tracking(bus))
    session = await SessionStore(db, clock).create(new_session(cwd=tmp_path, base_ref="abc"))

    await watcher.turn_started(session)

    assert not watcher.has_start(session.id)
    assert f"could not diff session {session.id} for review" in caplog.text
