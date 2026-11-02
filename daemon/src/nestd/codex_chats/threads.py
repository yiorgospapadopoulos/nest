"""Codex's threads as its app-server lists them (`thread/list`, `thread/turns/list`)."""

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import JsonValue

from nestd.providers.codex_items import items, obj, text
from nestd.providers.codex_rpc import CodexRpc, JsonObject

# Every source a thread can have but Codex's own sub-agents, whose threads never get a row.
# Without them Codex lists only the interactive ones (cli, vscode).
SOURCE_KINDS: list[JsonValue] = ["cli", "vscode", "exec", "appServer", "unknown"]
PAGE_SIZE = 100
# The pages read at most, should a cursor never end.
MAX_PAGES = 100
SUBAGENT = "subagent"
CUSTOM = "custom"


@dataclass(frozen=True)
class CodexThread:
    id: str
    name: str
    # Usually the first user message.
    preview: str
    cwd: Path
    created_at: datetime
    updated_at: datetime
    # Codex's source when it is a plain kind (`cli`, `vscode`, `exec`), else `custom` or
    # `subagent`.
    source: str
    originator: str | None
    # Set only for a sub-agent's thread.
    parent: str | None
    ephemeral: bool
    model: str | None
    archived: bool


def parse_thread(raw: JsonObject, *, archived: bool) -> CodexThread | None:
    """None for an entry without an id or a cwd."""
    thread_id, cwd = text(raw.get("id")), text(raw.get("cwd"))
    if not thread_id or not cwd:
        return None
    source = raw.get("source")
    if isinstance(source, str):
        kind = source
    elif isinstance(source, dict) and "subAgent" in source:
        kind = SUBAGENT
    else:
        kind = CUSTOM
    return CodexThread(
        id=thread_id,
        name=text(raw.get("name")).strip(),
        preview=text(raw.get("preview")).strip(),
        cwd=Path(unicodedata.normalize("NFC", cwd)),
        created_at=_time(raw.get("createdAt")),
        updated_at=_time(raw.get("updatedAt")),
        source=kind,
        originator=text(raw.get("originator")) or None,
        parent=text(raw.get("parentThreadId")) or None,
        ephemeral=raw.get("ephemeral") is True,
        model=text(raw.get("model")) or None,
        archived=archived,
    )


async def list_threads(rpc: CodexRpc) -> list[CodexThread]:
    """Every thread, the archived ones too (Codex lists them apart)."""
    threads: list[CodexThread] = []
    for archived in (False, True):
        cursor: JsonValue = None
        for _ in range(MAX_PAGES):
            page = await rpc.request(
                "thread/list",
                {
                    "archived": archived,
                    "cursor": cursor,
                    "limit": PAGE_SIZE,
                    "sourceKinds": SOURCE_KINDS,
                    "sortKey": "updated_at",
                },
            )
            threads.extend(
                thread
                for entry in items(page.get("data"))
                if (thread := parse_thread(obj(entry), archived=archived)) is not None
            )
            cursor = page.get("nextCursor")
            if not isinstance(cursor, str):
                break
    return threads


async def read_turns(rpc: CodexRpc, thread_id: str) -> list[JsonObject]:
    """The thread's turns, oldest first, with every item."""
    turns: list[JsonObject] = []
    cursor: JsonValue = None
    for _ in range(MAX_PAGES):
        page = await rpc.request(
            "thread/turns/list",
            {
                "threadId": thread_id,
                "cursor": cursor,
                "itemsView": "full",
                "sortDirection": "asc",
            },
        )
        turns.extend(obj(entry) for entry in items(page.get("data")))
        cursor = page.get("nextCursor")
        if not isinstance(cursor, str):
            break
    return turns


async def archive_thread(rpc: CodexRpc, thread_id: str, *, archived: bool) -> None:
    method = "thread/archive" if archived else "thread/unarchive"
    await rpc.request(method, {"threadId": thread_id})


def _time(value: JsonValue | None) -> datetime:
    seconds = value if isinstance(value, int | float) else 0
    return datetime.fromtimestamp(seconds, UTC)
