"""Flags running sessions that look stuck (D036).

The watcher follows every event live and keeps, for each turn in progress, when it began,
when the agent last did anything, which prompts it waits on and how often it repeated its
latest tool call. A session is stuck when, by the `[stuck]` settings, it waited on a prompt
too long, ran without output too long, repeated the same tool call too often, or ran one
turn too long. Several conditions can hold at once; the session shows the first of those,
in that order. Raising or changing the shown flag stores it on the session and publishes
`session.stuck`; the first time a reason shows in a turn it also notifies. When no
condition holds any more, `session.unstuck` follows. The end of the turn clears everything,
and a user message (a queued one, or a nudge) starts the count of a new turn.
"""

import asyncio
import json
import logging
from collections.abc import Callable
from contextlib import aclosing, suppress
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from harness.approvals.models import BLOCKING, ApprovalKind, ApprovalStatus
from harness.clock import Clock
from harness.config.models import StuckSettings
from harness.events import types
from harness.events.bus import EventBus, SubscriptionOverflowError
from harness.events.models import Event
from harness.notifications.notifier import Notifier
from harness.sessions.errors import SessionNotFoundError
from harness.sessions.models import SessionState
from harness.sessions.store import SessionStore
from harness.stuck.models import StuckFlag

logger = logging.getLogger(__name__)

TICK = timedelta(seconds=30)

# Events that show the agent (or the user answering it) doing something.
_ACTIVITY = frozenset(
    {
        types.SESSION_STATE,
        types.SESSION_USER_MESSAGE,
        types.SESSION_MESSAGE,
        types.SESSION_DELTA,
        # Thinking streams no text, and a notice (a retry, a compaction) shows the turn
        # is alive too (IMP-15, IMP-30).
        types.SESSION_THINKING,
        types.SESSION_NOTICE,
        types.SESSION_RESULT,
        types.SESSION_AGENT_TASK,
        types.APPROVAL_CREATED,
        types.APPROVAL_RESOLVED,
    }
)
_TURN_STATES = frozenset({SessionState.RUNNING.value, SessionState.WAITING.value})
_WAITING_ON = {
    ApprovalKind.PERMISSION.value: "your approval",
    ApprovalKind.QUESTION.value: "your answer",
    ApprovalKind.PLAN.value: "your plan review",
}


@dataclass
class _Repeat:
    key: str
    tool: str
    count: int
    since: datetime


@dataclass
class _Turn:
    started: datetime
    last_activity: datetime
    # Pending prompts the agent waits on: approval id to (created, kind).
    prompts: dict[str, tuple[datetime, str]] = field(
        default_factory=dict[str, tuple[datetime, str]]
    )
    # The latest tool call of the main agent (None) and of each subagent (its tool use id).
    repeats: dict[str | None, _Repeat] = field(default_factory=dict[str | None, _Repeat])
    # The main agent is thinking: no output, yet not silent.
    thinking: bool = False
    flag: StuckFlag | None = None
    # Reasons already notified in this turn.
    announced: set[str] = field(default_factory=set[str])


class StuckWatcher:
    def __init__(
        self,
        *,
        store: SessionStore,
        bus: EventBus,
        notifier: Notifier,
        clock: Clock,
        settings: Callable[[], StuckSettings],
        tick: timedelta = TICK,
    ) -> None:
        """`settings` is read at every check, so new thresholds apply at once."""
        self._store = store
        self._bus = bus
        self._notifier = notifier
        self._clock = clock
        self._settings = settings
        self._tick = tick
        self._turns: dict[str, _Turn] = {}
        self._tasks: list[asyncio.Task[None]] = []
        # One check at a time: a turn that ends during a tick is never flagged after (PL-02).
        self._checking = asyncio.Lock()

    async def start(self) -> None:
        """Clear flags a previous process left (its turns are over), then follow events."""
        for session_id in await self._store.clear_stuck():
            await self._bus.publish(types.SESSION_UNSTUCK, {"reason": None}, session_id)
        after = await self._bus.last_id()
        self._tasks = [
            asyncio.create_task(self._listen(after)),
            asyncio.create_task(self._ticks()),
        ]

    async def stop(self) -> None:
        tasks, self._tasks = self._tasks, []
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task

    async def observe(self, event: Event) -> None:
        """Follow one event; a condition that started or ended with it shows at once."""
        async with self._checking:
            await self._observe(event)

    async def tick(self) -> None:
        """Check every turn in progress, for conditions that grow with time."""
        async with self._checking:
            for session_id, turn in list(self._turns.items()):
                try:
                    await self._evaluate(session_id, turn)
                except SessionNotFoundError:
                    self._turns.pop(session_id, None)

    async def _observe(self, event: Event) -> None:
        if event.type == types.SESSION_DELETED:
            self._turns.pop(str(event.payload.get("session_id")), None)
            return
        session_id = event.session_id
        if session_id is None or event.type not in _ACTIVITY:
            return
        turn = self._turns.get(session_id)
        if event.type == types.SESSION_STATE:
            if event.payload.get("state") not in _TURN_STATES:
                await self._end(session_id)
                return
            if turn is None:
                turn = self._turns[session_id] = _Turn(started=event.ts, last_activity=event.ts)
        if turn is None:
            return
        turn.last_activity = event.ts
        if event.type == types.SESSION_USER_MESSAGE:
            # A queued message or a nudge starts the next turn without leaving `running`.
            turn.started = event.ts
            turn.thinking = False
            turn.repeats.clear()
            turn.announced.clear()
        elif event.type in (types.APPROVAL_CREATED, types.APPROVAL_RESOLVED):
            _note_prompt(turn, event)
        elif event.type == types.SESSION_MESSAGE:
            _note_calls(turn, event)
        if event.type == types.SESSION_THINKING:
            turn.thinking = event.payload.get("active") is True
        await self._evaluate(session_id, turn)

    async def _end(self, session_id: str) -> None:
        turn = self._turns.pop(session_id, None)
        if turn is not None and turn.flag is not None:
            await self._clear(session_id, turn.flag)

    async def _evaluate(self, session_id: str, turn: _Turn) -> None:
        flag = _condition(turn, self._settings(), self._clock.now())
        old = turn.flag
        if flag is None:
            if old is not None:
                turn.flag = None
                await self._clear(session_id, old)
            return
        if old is not None and (old.reason, old.since) == (flag.reason, flag.since):
            return
        turn.flag = flag
        session = await self._store.set_stuck(session_id, flag)
        await self._bus.publish(types.SESSION_STUCK, flag.model_dump(mode="json"), session_id)
        if flag.reason not in turn.announced:
            turn.announced.add(flag.reason)
            await self._notifier.notify(
                "stuck", session_id, session.repo, session.title, flag.details
            )

    async def _clear(self, session_id: str, old: StuckFlag) -> None:
        await self._store.set_stuck(session_id, None)
        await self._bus.publish(types.SESSION_UNSTUCK, {"reason": old.reason}, session_id)

    async def _listen(self, after: int) -> None:
        """Follow events stored after `after`; following again after falling behind starts
        after the last event seen, so none is missed (BUG-21).
        """
        while True:
            try:
                async with aclosing(self._bus.subscribe(after)) as events:
                    async for event in events:
                        after = event.id or after
                        try:
                            await self.observe(event)
                        except Exception as error:
                            logger.warning("stuck check failed (%s)", type(error).__name__)
            except SubscriptionOverflowError:
                logger.warning("the stuck watcher fell behind the events; following again")

    async def _ticks(self) -> None:
        while True:
            await asyncio.sleep(self._tick.total_seconds())
            try:
                await self.tick()
            except Exception as error:
                logger.warning("stuck check failed (%s)", type(error).__name__)


def _note_prompt(turn: _Turn, event: Event) -> None:
    approval = event.payload.get("approval")
    if not isinstance(approval, dict):
        return
    approval_id, kind = str(approval.get("id")), str(approval.get("kind"))
    if kind not in {k.value for k in BLOCKING}:
        return
    if approval.get("status") == ApprovalStatus.PENDING.value:
        turn.prompts[approval_id] = (event.ts, kind)
    else:
        turn.prompts.pop(approval_id, None)


def _note_calls(turn: _Turn, event: Event) -> None:
    parent = event.payload.get("parent_tool_use_id")
    owner = parent if isinstance(parent, str) else None
    blocks = event.payload.get("blocks")
    for block in blocks if isinstance(blocks, list) else []:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        tool = str(block.get("name"))
        key = tool + json.dumps(block.get("input"), sort_keys=True)
        current = turn.repeats.get(owner)
        if current is not None and current.key == key:
            current.count += 1
        else:
            turn.repeats[owner] = _Repeat(key=key, tool=tool, count=1, since=event.ts)


def _condition(turn: _Turn, settings: StuckSettings, now: datetime) -> StuckFlag | None:
    """The first condition that holds: waiting, repeating, silent, long turn."""
    if settings.waiting_minutes and turn.prompts:
        since, kind = min(turn.prompts.values())
        if now - since >= timedelta(minutes=settings.waiting_minutes):
            details = f"Waiting for {_WAITING_ON[kind]} for {_minutes(now - since)}"
            return StuckFlag(reason="waiting", since=since, details=details)
    if settings.repeated_calls:
        for repeat in turn.repeats.values():
            if repeat.count > settings.repeated_calls:
                details = f"Called {repeat.tool} {repeat.count} times in a row with the same input"
                return StuckFlag(reason="repeating", since=repeat.since, details=details)
    quiet = now - turn.last_activity
    if (
        settings.silent_minutes
        and not turn.prompts
        and not turn.thinking
        and quiet >= timedelta(minutes=settings.silent_minutes)
    ):
        details = f"No new output for {_minutes(quiet)}"
        return StuckFlag(reason="silent", since=turn.last_activity, details=details)
    running = now - turn.started
    if settings.turn_minutes and running >= timedelta(minutes=settings.turn_minutes):
        details = f"The turn has run for {_minutes(running)}"
        return StuckFlag(reason="long_turn", since=turn.started, details=details)
    return None


def _minutes(delta: timedelta) -> str:
    count = int(delta.total_seconds() // 60)
    return "1 minute" if count == 1 else f"{count} minutes"
