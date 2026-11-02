"""Subagents (C11), over the last 30 days: how many subagent replies a main turn brings,
and the tokens inside subagents against the main chats'."""

from nestd.clock import Clock
from nestd.perf.collectors.common import since
from nestd.perf.models import Collected, Measured
from nestd.storage.db import Database

DAYS = 30


class Subagents:
    def __init__(self, db: Database, clock: Clock) -> None:
        self._db = db
        self._clock = clock

    async def __call__(self) -> Collected:
        rows = await self._db.fetch_all(
            "SELECT subagent, COUNT(*) AS n, SUM(input_tokens + output_tokens"
            " + cache_creation_input_tokens + cache_read_input_tokens) AS tokens"
            " FROM turn_usage WHERE ts >= ? GROUP BY subagent",
            (since(self._clock, DAYS).isoformat(),),
        )
        by_kind = {bool(row["subagent"]): (row["n"], row["tokens"] or 0) for row in rows}
        turns, main_tokens = by_kind.get(False, (0, 0))
        messages, sub_tokens = by_kind.get(True, (0, 0))
        everything = main_tokens + sub_tokens
        return Collected(
            metrics=[
                Measured(
                    id="per_turn",
                    label="Subagent replies per turn",
                    unit="count",
                    better="none",
                    value=messages / turns if turns else None,
                ),
                Measured(
                    id="subagent_tokens",
                    label="Tokens in subagents",
                    unit="tokens",
                    better="none",
                    value=sub_tokens,
                ),
                Measured(
                    id="main_tokens",
                    label="Tokens in the main chats",
                    unit="tokens",
                    better="none",
                    value=main_tokens,
                ),
                Measured(
                    id="share",
                    label="Share in subagents",
                    unit="percent",
                    better="none",
                    value=sub_tokens / everything * 100 if everything else None,
                ),
                Measured(
                    id="per_message",
                    label="Tokens per subagent reply",
                    unit="tokens",
                    better="lower",
                    value=sub_tokens / messages if messages else None,
                ),
            ]
        )
