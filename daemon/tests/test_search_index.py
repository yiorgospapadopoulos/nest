import asyncio
import logging
from contextlib import AbstractAsyncContextManager
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import JsonValue

from harness.claude_sessions.models import ClaudeChat
from harness.events import types
from harness.events.bus import EventBus
from harness.search.index import SearchIndex
from harness.search.models import SearchHit
from harness.sessions.models import Session
from harness.sessions.store import SessionStore
from harness.storage.db import Database, Transaction
from tests.async_support import until
from tests.fakes import FakeClock
from tests.test_session_store import new_session


class Env:
    def __init__(self, db: Database, clock: FakeClock) -> None:
        self.db = db
        self.clock = clock
        self.bus = EventBus(db, clock)
        self.store = SessionStore(db, clock)
        self.index = SearchIndex(db, batch=3, interval=timedelta(milliseconds=10))

    async def session(self, title: str = "Fix the login page", repo: str = "repo") -> Session:
        """A session announced the way the session manager does."""
        session = await self.store.create(new_session(title=title, repo=repo))
        await self.bus.publish(
            types.SESSION_CREATED, {"session": session.model_dump(mode="json")}, session.id
        )
        return session

    async def say(self, session: Session, text: str, user: bool = False) -> int:
        if user:
            event = await self.bus.publish(
                types.SESSION_USER_MESSAGE, {"text": text, "attachments": []}, session.id
            )
        else:
            blocks: list[JsonValue] = [{"type": "text", "text": text}]
            event = await self.bus.publish(
                types.SESSION_MESSAGE, {"blocks": blocks, "parent_tool_use_id": None}, session.id
            )
        assert event.id is not None
        return event.id

    async def rename(self, session: Session, title: str) -> None:
        renamed = await self.store.update(session.id, title=title)
        await self.bus.publish(
            types.SESSION_UPDATED,
            {"changes": {"title": title}, "session": renamed.model_dump(mode="json")},
            session.id,
        )

    async def hits(self, text: str, repo: str | None = None, limit: int = 20) -> list[SearchHit]:
        await self.index.catch_up()
        return (await self.index.search(text, repo, limit)).hits


@pytest.fixture
def env(db: Database, clock: FakeClock) -> Env:
    return Env(db, clock)


def chat(chat_id: str, title: str, automated: bool = False, minutes: int = 0) -> ClaudeChat:
    return ClaudeChat(
        id=chat_id,
        repo="repo",
        title=title,
        cwd=Path("/r"),
        worktree=None,
        created_at=FakeClock().now(),
        last_activity_at=FakeClock().now() + timedelta(minutes=minutes),
        message_count=2,
        open_in_claude_code=False,
        entrypoint="sdk-py" if automated else "cli",
        automated=automated,
    )


async def test_messages_and_titles_are_found_with_highlighted_snippets(env: Env) -> None:
    session = await env.session()
    asked = await env.say(session, "Please check the password reset", user=True)
    await env.say(session, "The password reset mail was never sent.")

    hits = await env.hits("password")

    assert [(h.kind, h.event_id) for h in hits] == [("user", asked), ("assistant", asked + 1)]
    first = hits[0]
    assert first.session_id == session.id
    assert (first.repo, first.title) == ("repo", "Fix the login page")
    assert first.snippet == "Please check the [[password]] reset"
    assert first.ts == env.clock.now()
    (title,) = await env.hits("login")
    assert (title.kind, title.event_id, title.snippet) == ("title", None, "Fix the [[login]] page")


async def test_better_matches_rank_first_then_newer_ones(env: Env) -> None:
    session = await env.session(title="Unrelated")
    weak = await env.say(session, "deploy " + "filler words here " * 30)
    old = await env.say(session, "deploy failed")
    env.clock.advance(timedelta(minutes=1))
    new = await env.say(session, "deploy failed")

    hits = await env.hits("deploy")

    assert [h.event_id for h in hits] == [new, old, weak]


async def test_phrases_prefixes_and_every_word(env: Env) -> None:
    session = await env.session(title="Unrelated")
    both = await env.say(session, "the cache layer broke the build")
    phrase = await env.say(session, "a build cache")
    await env.say(session, "only cache here")

    assert {h.event_id for h in await env.hits("cache build")} == {both, phrase}
    assert [h.event_id for h in await env.hits('"build cache"')] == [phrase]
    assert {h.event_id for h in await env.hits("bui*")} == {both, phrase}
    assert await env.hits("bui") == []


async def test_syntax_and_empty_queries_return_nothing(env: Env) -> None:
    session = await env.session(title="Unrelated")
    await env.say(session, "NOT a problem")

    assert [h.kind for h in await env.hits("NOT")] == ["assistant"]
    assert await env.hits('"') == []
    assert await env.hits("***") == []


async def test_repo_filter_and_limit(env: Env) -> None:
    mine = await env.session(title="Bug one", repo="app")
    await env.session(title="Bug two", repo="site")
    await env.index.sync_claude_chats([chat("c1", "Bug three")])

    assert [h.title for h in await env.hits("bug", repo="app")] == ["Bug one"]
    assert [h.title for h in await env.hits("bug", repo="repo")] == ["Bug three"]
    assert len(await env.hits("bug", limit=2)) == 2
    assert mine.repo == "app"


async def test_renames_replace_the_title(env: Env) -> None:
    session = await env.session(title="Old name")
    await env.say(session, "anything")
    await env.rename(session, "Fresh name")
    other = await env.bus.publish(
        types.SESSION_UPDATED, {"changes": {"pinned": True}, "session": {}}, session.id
    )

    assert await env.hits("old") == []
    (hit,) = await env.hits("fresh")
    assert hit.title == "Fresh name"
    assert other.id is not None
    # The title of message hits is the session's current one.
    (message,) = await env.hits("anything")
    assert message.title == "Fresh name"


async def test_deleted_sessions_leave_the_index(env: Env) -> None:
    gone = await env.session(title="Gone chat")
    await env.say(gone, "secret plan")
    kept = await env.session(title="Kept chat")
    await env.say(kept, "secret recipe")
    await env.index.catch_up()

    await env.store.delete(gone.id)
    # Found nowhere even before the deletion event is indexed.
    assert [h.session_id for h in (await env.index.search("secret", None, 20)).hits] == [kept.id]
    await env.bus.publish(types.SESSION_DELETED, {"session_id": gone.id})
    await env.index.catch_up()
    rows = await env.db.fetch_all(
        "SELECT COUNT(*) AS n FROM search_index WHERE session_id = ?", (gone.id,)
    )
    assert rows[0]["n"] == 0


async def test_backfill_runs_in_batches_and_reports_progress(env: Env) -> None:
    session = await env.session(title="Unrelated")
    for n in range(7):
        await env.say(session, f"note {n}")

    assert (await env.index.search("note", None, 20)).indexing is True
    await env.index.catch_up()

    results = await env.index.search("note", None, 20)
    assert (len(results.hits), results.indexing) == (7, False)
    cursor = await env.db.fetch_one("SELECT cursor FROM search_state")
    assert cursor is not None
    assert cursor["cursor"] == await env.bus.last_id()


async def test_after_the_backfill_a_search_indexes_new_events_first(env: Env) -> None:
    session = await env.session(title="Unrelated")
    await env.index.catch_up()
    fresh = await env.say(session, "just said")

    hits = (await env.index.search("said", None, 20)).hits

    assert [h.event_id for h in hits] == [fresh]


async def test_the_background_loop_keeps_up_and_logs_failures(
    env: Env, caplog: pytest.LogCaptureFixture
) -> None:
    session = await env.session(title="Unrelated")
    await env.say(session, "early bird")
    calls = 0
    real = env.index.catch_up

    async def flaky() -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        await real()

    env.index.catch_up = flaky  # type: ignore[method-assign]
    with caplog.at_level(logging.WARNING):
        await env.index.start()
        try:
            await until(lambda: calls >= 2)
            await env.say(session, "late owl")

            async def found() -> bool:
                return len((await env.index.search("owl", None, 20)).hits) == 1

            await until(found)
        finally:
            await env.index.stop()
            await env.index.stop()
    assert "search indexing failed (RuntimeError)" in caplog.text


async def test_claude_code_chat_titles_are_found_until_they_leave_the_list(env: Env) -> None:
    await env.index.sync_claude_chats(
        [chat("c1", "Refactor parser"), chat("c2", "Parser bot", automated=True)]
    )

    (hit,) = await env.hits("parser")
    assert (hit.session_id, hit.kind, hit.event_id, hit.title, hit.repo) == (
        "c1",
        "claude_chat",
        None,
        "Refactor parser",
        "repo",
    )

    await env.index.sync_claude_chats([chat("c1", "Rewrite parser", minutes=5)])
    (renamed,) = await env.hits("parser")
    assert renamed.title == "Rewrite parser"
    assert renamed.ts == FakeClock().now() + timedelta(minutes=5)

    await env.index.sync_claude_chats([])
    assert await env.hits("parser") == []


async def test_unchanged_chat_lists_write_nothing_and_survive_a_restart(
    env: Env, db: Database
) -> None:
    await env.index.sync_claude_chats([chat("c1", "Refactor parser")])
    writes = 0
    real = db.transaction

    def counting() -> AbstractAsyncContextManager[Transaction]:
        nonlocal writes
        writes += 1
        return real()

    db.transaction = counting  # type: ignore[method-assign]
    await env.index.sync_claude_chats([chat("c1", "Refactor parser")])
    assert writes == 0
    db.transaction = real  # type: ignore[method-assign]

    restarted = SearchIndex(db)
    await restarted.sync_claude_chats([chat("c1", "Refactor parser"), chat("c3", "New one")])
    rows = await db.fetch_all("SELECT session_id FROM search_index WHERE kind = 'claude_chat'")
    assert sorted(row["session_id"] for row in rows) == ["c1", "c3"]


async def test_stop_before_start_is_harmless(env: Env) -> None:
    await env.index.stop()
    await asyncio.sleep(0)


async def test_global_events_and_odd_session_payloads_are_skipped(env: Env) -> None:
    session = await env.session(title="Unrelated")
    await env.bus.publish(types.DAEMON_STARTED, {"version": "plan"})
    await env.bus.publish(types.SESSION_CREATED, {"session": "plan"}, session.id)
    await env.bus.publish(
        types.SESSION_UPDATED, {"changes": {"title": 1}, "session": {}}, session.id
    )

    assert await env.hits("plan") == []
    assert [h.kind for h in await env.hits("unrelated")] == ["title"]
