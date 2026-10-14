"""The search index: kept current from the stored events, queried with FTS5 (D035).

The indexer reads events after its cursor in small batches, each in its own transaction,
so the first pass over a long history never holds the database for long. Once that pass is
done, each search first indexes whatever was stored since.
"""

import asyncio
import json
import logging
import sqlite3
from contextlib import suppress
from datetime import datetime, timedelta

from pydantic import JsonValue

from nestd.claude_sessions.models import ClaudeChat
from nestd.events import types
from nestd.search.entries import entries
from nestd.search.models import SearchHit, SearchResults
from nestd.search.query import fts_query
from nestd.storage.db import Database, Transaction

logger = logging.getLogger(__name__)

BATCH = 200
INTERVAL = timedelta(seconds=5)
_SNIPPET_TOKENS = 12

type _ChatRow = tuple[str, str, str]  # repo, title, ts

_SEARCH = f"""
SELECT search_index.session_id AS session_id, kind, event_id, search_index.ts AS ts,
    COALESCE(sessions.repo, search_index.repo) AS repo,
    COALESCE(sessions.title, search_index.text) AS title,
    snippet(search_index, 0, '[[', ']]', '…', {_SNIPPET_TOKENS}) AS snippet
FROM search_index LEFT JOIN sessions ON sessions.id = search_index.session_id
WHERE search_index MATCH ?
    AND (sessions.id IS NOT NULL OR kind = 'claude_chat')
    AND (? IS NULL OR COALESCE(sessions.repo, search_index.repo) = ?)
ORDER BY bm25(search_index), search_index.ts DESC
LIMIT ?
"""  # noqa: S608 (constants only)


class SearchIndex:
    def __init__(self, db: Database, batch: int = BATCH, interval: timedelta = INTERVAL) -> None:
        self._db = db
        self._batch = batch
        self._interval = interval
        self._caught_up = False
        # The Claude Code chats in the index, loaded on first use.
        self._chats: dict[str, _ChatRow] | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def catch_up(self) -> None:
        """Index every event stored after the cursor, one batch per transaction."""
        while True:
            async with self._db.transaction() as tx:
                state = await tx.fetch_one("SELECT cursor FROM search_state")
                rows = await tx.fetch_all(
                    "SELECT id, type, ts, session_id, payload FROM events WHERE id > ?"
                    " ORDER BY id LIMIT ?",
                    (state["cursor"] if state is not None else 0, self._batch),
                )
                for row in rows:
                    await _index(tx, row)
                if rows:
                    await tx.execute("UPDATE search_state SET cursor = ?", (rows[-1]["id"],))
            if len(rows) < self._batch:
                self._caught_up = True
                return
            # Let everything else run between batches.
            await asyncio.sleep(0)

    async def search(self, text: str, repo: str | None, limit: int) -> SearchResults:
        if self._caught_up:
            await self.catch_up()
        query = fts_query(text)
        if query is None:
            return SearchResults(hits=[], indexing=not self._caught_up)
        rows = await self._db.fetch_all(_SEARCH, (query, repo, repo, limit))
        hits = [
            SearchHit(
                session_id=row["session_id"],
                repo=row["repo"],
                title=row["title"],
                event_id=row["event_id"],
                ts=datetime.fromisoformat(row["ts"]),
                kind=row["kind"],
                snippet=" ".join(row["snippet"].split()),
            )
            for row in rows
        ]
        return SearchResults(hits=hits, indexing=not self._caught_up)

    async def sync_claude_chats(self, chats: list[ClaudeChat]) -> None:
        """Index the titles of the listed Claude Code chats, automated ones left out."""
        wanted = {
            chat.id: (chat.repo, chat.title, chat.last_activity_at.isoformat())
            for chat in chats
            if not chat.automated
        }
        if self._chats is None:
            rows = await self._db.fetch_all(
                "SELECT session_id, repo, text, ts FROM search_index WHERE kind = 'claude_chat'"
            )
            self._chats = {row["session_id"]: (row["repo"], row["text"], row["ts"]) for row in rows}
        known = self._chats
        if wanted == known:
            return
        async with self._db.transaction() as tx:
            for chat_id in known.keys() - wanted.keys():
                await _delete_chat(tx, chat_id)
            for chat_id, row in wanted.items():
                if known.get(chat_id) != row:
                    await _delete_chat(tx, chat_id)
                    await _insert(tx, row[1], "claude_chat", chat_id, row[2], repo=row[0])
        self._chats = wanted

    async def _loop(self) -> None:
        while True:
            try:
                await self.catch_up()
            except Exception as error:
                logger.warning("search indexing failed (%s)", type(error).__name__)
            await asyncio.sleep(self._interval.total_seconds())


async def _index(tx: Transaction, row: sqlite3.Row) -> None:
    event_type: str = row["type"]
    session_id: str | None = row["session_id"]
    if event_type == types.SESSION_DELETED:
        deleted = json.loads(row["payload"]).get("session_id")
        await tx.execute(
            "DELETE FROM search_index WHERE session_id = ? AND kind != 'claude_chat'", (deleted,)
        )
        return
    if session_id is None:
        return
    payload: dict[str, JsonValue] = json.loads(row["payload"])
    if event_type in (types.SESSION_CREATED, types.SESSION_UPDATED):
        await _index_title(tx, event_type, payload, session_id, row["ts"])
        return
    for entry in entries(event_type, payload):
        await _insert(tx, entry.text, entry.kind, session_id, row["ts"], event_id=row["id"])


async def _index_title(
    tx: Transaction, event_type: str, payload: dict[str, JsonValue], session_id: str, ts: str
) -> None:
    changes = payload.get("changes")
    if event_type == types.SESSION_UPDATED and not (
        isinstance(changes, dict) and "title" in changes
    ):
        return
    session = payload.get("session")
    title = session.get("title") if isinstance(session, dict) else None
    if not isinstance(title, str):
        return
    await tx.execute(
        "DELETE FROM search_index WHERE session_id = ? AND kind = 'title'", (session_id,)
    )
    await _insert(tx, title, "title", session_id, ts)


async def _insert(
    tx: Transaction,
    text: str,
    kind: str,
    session_id: str,
    ts: str,
    *,
    event_id: int | None = None,
    repo: str | None = None,
) -> None:
    await tx.execute(
        "INSERT INTO search_index (text, kind, session_id, repo, event_id, ts)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (text, kind, session_id, repo, event_id, ts),
    )


async def _delete_chat(tx: Transaction, chat_id: str) -> None:
    await tx.execute(
        "DELETE FROM search_index WHERE session_id = ? AND kind = 'claude_chat'", (chat_id,)
    )
