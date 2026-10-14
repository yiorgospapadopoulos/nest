"""Publishes `notify` events: things the user should hear about, whatever the channel."""

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import JsonValue

from harness.events import types
from harness.events.bus import EventBus
from harness.sessions.models import PIXIE_REPO_PREFIX

type NotifyKind = Literal[
    "needs_approval",
    "question",
    "review_ready",
    "failed",
    "finished",
    "ci_failed",
    "ready_to_merge",
    "stuck",
    "pixie_report",
]


# A pixie's name by its id, or None once it is gone.
type PixieName = Callable[[str], Awaitable[str | None]]


class Notifier:
    def __init__(self, bus: EventBus, pixie_name: PixieName | None = None) -> None:
        self._bus = bus
        self._pixie_name = pixie_name

    async def notify(
        self,
        kind: NotifyKind,
        session_id: str,
        repo: str,
        title: str,
        text: str,
        extra: dict[str, JsonValue] | None = None,
    ) -> None:
        """`extra` adds fields of the kind, such as a pixie report's id (B42)."""
        payload: dict[str, JsonValue] = {
            "kind": kind,
            "session_id": session_id,
            "repo": repo,
            "title": title,
            "text": text,
            **(extra or {}),
        }
        if repo.startswith(PIXIE_REPO_PREFIX):
            # A pixie's chat: the phone names the pixie and opens its page (D072).
            pixie_id = repo.removeprefix(PIXIE_REPO_PREFIX)
            payload["pixie_id"] = pixie_id
            name = None if self._pixie_name is None else await self._pixie_name(pixie_id)
            if name is not None:
                payload["pixie_name"] = name
        await self._bus.publish(types.NOTIFY, payload, session_id)
