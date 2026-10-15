from datetime import timedelta
from pathlib import Path

import pytest

from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import NewSession, SessionState
from nestd.sessions.store import SessionStore
from nestd.storage.db import Database
from nestd.stuck.models import StuckFlag
from tests.fakes import FakeClock


def new_session(**overrides: object) -> NewSession:
    values: dict[str, object] = {
        "repo": "repo",
        "title": "Fix it",
        "prompt": "Fix it please",
        "mode": "worktree",
        "cwd": None,
        "model": "claude-sonnet-5",
        "effort": "high",
        "permission_mode": "default",
        "provider": "fake",
    }
    values.update(overrides)
    return NewSession.model_validate(values)


@pytest.fixture
def store(db: Database, clock: FakeClock) -> SessionStore:
    return SessionStore(db, clock)


async def test_create_and_get(store: SessionStore, clock: FakeClock) -> None:
    session = await store.create(new_session())

    assert len(session.id) == 32
    assert session.state is SessionState.STARTING
    assert session.created_at == session.updated_at == clock.current
    assert session.provider_session_id is None
    assert session.base_ref is None
    assert (session.commit_sha, session.pr_url, session.allowed_tools) == (None, None, [])
    assert await store.get(session.id) == session


async def test_sessions_no_longer_store_a_git_violation(db: Database) -> None:
    """B58: the agent's own commits are no violation, so the flag's column is gone."""
    columns = {row["name"] for row in await db.fetch_all("PRAGMA table_info(sessions)")}

    assert "git_violation" not in columns
    assert {"base_ref", "commit_sha"} <= columns


async def test_an_in_place_session_records_its_starting_commit(store: SessionStore) -> None:
    session = await store.create(new_session(mode="in_place", base_ref="abc123"))

    assert (await store.get(session.id)).base_ref == "abc123"


async def test_review_fields_round_trip(store: SessionStore) -> None:
    session = await store.create(new_session())

    updated = await store.update(
        session.id, commit_sha="c0ffee", pr_url="https://x/pull/1", allowed_tools=["Edit", "Bash"]
    )

    assert (updated.commit_sha, updated.pr_url) == ("c0ffee", "https://x/pull/1")
    assert updated.allowed_tools == ["Edit", "Bash"]
    assert await store.get(session.id) == updated


async def test_update_changes_fields_and_timestamp(store: SessionStore, clock: FakeClock) -> None:
    session = await store.create(new_session(mode="in_place", cwd=Path("/repo")))
    clock.advance(timedelta(seconds=5))

    updated = await store.update(
        session.id,
        state=SessionState.IDLE,
        worktree_path=Path("/wt"),
        last_error="it broke",
    )

    assert updated.state is SessionState.IDLE
    assert updated.worktree_path == Path("/wt")
    assert updated.cwd == Path("/repo")
    assert updated.last_error == "it broke"
    assert updated.updated_at == clock.current
    assert updated.created_at == session.created_at


async def test_unknown_sessions(store: SessionStore) -> None:
    with pytest.raises(SessionNotFoundError, match="unknown session 'nope'"):
        await store.get("nope")
    with pytest.raises(SessionNotFoundError):
        await store.update("nope", state=SessionState.IDLE)


async def test_list_is_pinned_first_then_most_recently_updated(
    store: SessionStore, clock: FakeClock
) -> None:
    first = await store.create(new_session())
    clock.advance(timedelta(seconds=1))
    second = await store.create(new_session())
    clock.advance(timedelta(seconds=1))
    third = await store.create(new_session())
    clock.advance(timedelta(seconds=1))
    await store.update(first.id, state=SessionState.IDLE)
    await store.update(second.id, pinned=True)

    assert [s.id for s in await store.list_sessions()] == [second.id, first.id, third.id]


async def test_list_filters_by_repo_and_archived(store: SessionStore, clock: FakeClock) -> None:
    kept = await store.create(new_session())
    other = await store.create(new_session(repo="other"))
    archived = await store.create(new_session())
    await store.update(archived.id, archived_at=clock.now())

    assert [s.id for s in await store.list_sessions(repo="repo")] == [kept.id]
    assert [s.id for s in await store.list_sessions(repo="repo", archived=True)] == [archived.id]
    assert {s.id for s in await store.list_sessions()} == {kept.id, other.id}
    assert (await store.get(archived.id)).archived_at == clock.now()
    assert (await store.get(kept.id)).pinned is False


async def test_delete_removes_the_session_with_its_approvals_attachments_and_events(
    store: SessionStore, db: Database, clock: FakeClock
) -> None:
    doomed = await store.create(new_session())
    kept = await store.create(new_session())
    for session_id in (doomed.id, kept.id):
        await store.keep_earlier_provider_session(session_id, f"sdk-{session_id}")
        await db.execute(
            "INSERT INTO approvals (id, session_id, kind, status, payload, created_at)"
            " VALUES (?, ?, 'review', 'pending', '{}', ?)",
            (f"a-{session_id}", session_id, clock.now().isoformat()),
        )
        await db.execute(
            "INSERT INTO attachments (id, session_id, filename, media_type, path, size, created_at)"
            " VALUES (?, ?, 'f', 'text/plain', '/f', 1, ?)",
            (f"f-{session_id}", session_id, clock.now().isoformat()),
        )
        await db.execute(
            "INSERT INTO events (type, ts, session_id, payload) VALUES ('x', ?, ?, '{}')",
            (clock.now().isoformat(), session_id),
        )

    await store.delete(doomed.id)

    with pytest.raises(SessionNotFoundError):
        await store.get(doomed.id)
    assert await store.get(kept.id) == kept
    for table in ("approvals", "attachments", "events", "earlier_provider_sessions"):
        rows = await db.fetch_all(f"SELECT session_id FROM {table}")  # noqa: S608
        assert [row["session_id"] for row in rows] == [kept.id]


async def test_in_flight_sessions_become_interrupted(store: SessionStore) -> None:
    states = list(SessionState)
    sessions = [await store.create(new_session()) for _ in states]
    for session, state in zip(sessions, states, strict=True):
        await store.update(session.id, state=state)

    interrupted = await store.interrupt_in_flight()

    in_flight = {SessionState.STARTING, SessionState.RUNNING, SessionState.WAITING}
    assert sorted(interrupted) == sorted(
        s.id for s, state in zip(sessions, states, strict=True) if state in in_flight
    )
    after = {s.id: s.state for s in await store.list_sessions()}
    for session, state in zip(sessions, states, strict=True):
        expected = SessionState.INTERRUPTED if state in in_flight else state
        assert after[session.id] is expected


async def test_stuck_flags_are_stored_without_reordering_and_cleared_together(
    store: SessionStore, clock: FakeClock
) -> None:
    first = await store.create(new_session())
    second = await store.create(new_session())
    clock.advance(timedelta(minutes=5))
    flag = StuckFlag(reason="silent", since=clock.now(), details="No new output for 10 minutes")

    flagged = await store.set_stuck(first.id, flag)
    await store.set_stuck(second.id, flag)
    cleared = await store.set_stuck(second.id, None)

    assert flagged.stuck == flag
    assert flagged.updated_at == first.updated_at
    assert cleared.stuck is None
    assert await store.clear_stuck() == [first.id]
    assert (await store.get(first.id)).stuck is None
    assert await store.clear_stuck() == []


async def test_chats_a_pixie_started_and_its_open_batches(
    store: SessionStore, clock: FakeClock
) -> None:
    first = await store.create(new_session(started_by_pixie="p1", pixie_batch="b1"))
    clock.advance(timedelta(minutes=1))
    second = await store.create(new_session(started_by_pixie="p1", pixie_batch="b2"))
    other = await store.create(new_session(started_by_pixie="p2", pixie_batch="b3"))
    await store.create(new_session())
    before = (await store.get(first.id)).updated_at
    clock.advance(timedelta(minutes=1))

    started = await store.started_by("p1")
    batched = await store.batch_members("p1")
    pixies = await store.batch_pixies()
    await store.clear_batch([first.id, other.id])

    assert [s.id for s in started] == [first.id, second.id]
    assert [s.id for s in batched] == [first.id, second.id]
    assert pixies == ["p1", "p2"]
    assert [s.id for s in await store.batch_members("p1")] == [second.id]
    assert await store.batch_pixies() == ["p1"]
    # Clearing a batch does not move a chat up its list.
    assert (await store.get(first.id)).updated_at == before
    assert (await store.get(first.id)).started_by_pixie == "p1"
