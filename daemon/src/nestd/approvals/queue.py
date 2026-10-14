"""The approval queue: items are stored, announced as events, and resolved through the API.

An agent run waiting on a permission or question holds a future that the resolution
completes. Reviews have no waiter; the review actions resolve them.
"""

import asyncio
from collections.abc import Awaitable, Callable, Sequence

from pydantic import JsonValue

from nestd.approvals.errors import ApprovalNotPendingError
from nestd.approvals.models import BLOCKING, Approval, ApprovalKind, ApprovalStatus
from nestd.approvals.store import ApprovalStore
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.notifications.notifier import Notifier, NotifyKind

# Told whether the session still has a run waiting, after each change.
type WaitingCallback = Callable[[bool], Awaitable[None]]

_NOTICE: dict[ApprovalKind, NotifyKind] = {
    ApprovalKind.PERMISSION: "needs_approval",
    ApprovalKind.QUESTION: "question",
    # A plan blocks the agent like a question does.
    ApprovalKind.PLAN: "question",
    ApprovalKind.REVIEW: "review_ready",
    ApprovalKind.MERGE: "ready_to_merge",
}


class ApprovalQueue:
    def __init__(self, store: ApprovalStore, bus: EventBus, notifier: Notifier) -> None:
        self._store = store
        self._bus = bus
        self._notifier = notifier
        # Approval id to (session id, future) for items an agent run is waiting on.
        self._waiters: dict[str, tuple[str, asyncio.Future[Approval]]] = {}

    async def get(self, approval_id: str) -> Approval:
        return await self._store.get(approval_id)

    async def list_approvals(
        self, status: ApprovalStatus | None = None, repo: str | None = None
    ) -> list[Approval]:
        return await self._store.list_approvals(status, repo)

    async def pending(self, session_id: str, kind: ApprovalKind) -> Approval | None:
        items = await self._store.pending((kind,), session_id)
        return items[-1] if items else None

    def waiting(self, session_id: str) -> bool:
        """Whether an agent run of the session is waiting on an item."""
        return any(owner == session_id for owner, _ in self._waiters.values())

    async def wait(
        self,
        session_id: str,
        kind: ApprovalKind,
        payload: dict[str, JsonValue],
        notice: str,
        on_waiting: WaitingCallback,
    ) -> Approval:
        """Create an item and wait until it is resolved or expired; return its final state."""
        approval = await self._create(session_id, kind, payload, notice)
        future = asyncio.get_running_loop().create_future()
        self._waiters[approval.id] = (session_id, future)
        try:
            await on_waiting(True)
            return await future
        finally:
            del self._waiters[approval.id]
            # A resolution that came just before the waiting task was cancelled still counts.
            if not (future.done() and not future.cancelled()):
                await self._close(approval.id, ApprovalStatus.EXPIRED, {"reason": "cancelled"})
            await on_waiting(self.waiting(session_id))

    async def add(
        self, session_id: str, kind: ApprovalKind, payload: dict[str, JsonValue], notice: str
    ) -> Approval:
        """Create an item nothing waits on, replacing the session's pending one of its kind."""
        await self.supersede(session_id, kind)
        return await self._create(session_id, kind, payload, notice)

    async def resolve(self, approval_id: str, resolution: dict[str, JsonValue]) -> Approval:
        approval = await self._close(approval_id, ApprovalStatus.RESOLVED, resolution)
        if approval is None:
            current = await self._store.get(approval_id)
            msg = f"approval {approval_id!r} is {current.status}"
            raise ApprovalNotPendingError(msg)
        return approval

    async def supersede(self, session_id: str, kind: ApprovalKind) -> None:
        for approval in await self._store.pending((kind,), session_id):
            await self._close(approval.id, ApprovalStatus.SUPERSEDED, None)

    async def expire(self, session_id: str, kinds: Sequence[ApprovalKind], reason: str) -> None:
        for approval in await self._store.pending(kinds, session_id):
            await self._close(approval.id, ApprovalStatus.EXPIRED, {"reason": reason})

    async def expire_stale(self) -> None:
        """On startup, nothing waits on permissions or questions any more; reviews stay."""
        for approval in await self._store.pending(BLOCKING):
            await self._close(
                approval.id, ApprovalStatus.EXPIRED, {"reason": "the daemon restarted"}
            )

    async def _create(
        self, session_id: str, kind: ApprovalKind, payload: dict[str, JsonValue], notice: str
    ) -> Approval:
        approval = await self._store.create(session_id, kind, payload)
        await self._bus.publish(
            types.APPROVAL_CREATED, {"approval": approval.model_dump(mode="json")}, session_id
        )
        await self._notifier.notify(
            _NOTICE[kind], session_id, approval.repo, approval.title, notice
        )
        return approval

    async def _close(
        self,
        approval_id: str,
        status: ApprovalStatus,
        resolution: dict[str, JsonValue] | None,
    ) -> Approval | None:
        approval = await self._store.close(approval_id, status, resolution)
        if approval is None:
            return None
        await self._bus.publish(
            types.APPROVAL_RESOLVED,
            {"approval": approval.model_dump(mode="json")},
            approval.session_id,
        )
        waiter = self._waiters.get(approval_id)
        if waiter is not None and not waiter[1].done():
            waiter[1].set_result(approval)
        return approval
