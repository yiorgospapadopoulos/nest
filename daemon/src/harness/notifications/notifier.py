"""Publishes `notify` events: things the user should hear about, whatever the channel."""

from typing import Literal

from harness.events import types
from harness.events.bus import EventBus

type NotifyKind = Literal[
    "needs_approval",
    "question",
    "review_ready",
    "failed",
    "finished",
    "ci_failed",
    "ready_to_merge",
    "stuck",
]


class Notifier:
    def __init__(self, bus: EventBus) -> None:
        self._bus = bus

    async def notify(
        self, kind: NotifyKind, session_id: str, repo: str, title: str, text: str
    ) -> None:
        await self._bus.publish(
            types.NOTIFY,
            {"kind": kind, "session_id": session_id, "repo": repo, "title": title, "text": text},
            session_id,
        )
