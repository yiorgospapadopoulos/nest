from datetime import datetime
from typing import Literal

from pydantic import BaseModel

type HitKind = Literal[
    "title", "user", "assistant", "tool", "tool_result", "claude_chat", "codex_chat"
]


class SearchHit(BaseModel):
    # A Nest session, or a Claude Code or Codex chat Nest does not own (kind claude_chat
    # or codex_chat).
    session_id: str
    repo: str
    # The chat's current title.
    title: str
    # The event to scroll to; None for title matches.
    event_id: int | None
    ts: datetime
    kind: HitKind
    # Matched words are wrapped in [[ and ]]; cut text is marked with an ellipsis.
    snippet: str


class SearchResults(BaseModel):
    # Best match first; equal matches newest first.
    hits: list[SearchHit]
    # True while the first pass over the stored history is still running.
    indexing: bool
