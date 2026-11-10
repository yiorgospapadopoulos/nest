"""Keeps chats on Autopilot going.

A run is stored on its session, so it survives a restart. Every tick looks at each run: a
budget that ran out ends it, a chat that went quiet gets a nudge, and a chat that rests gets
the message that lets it go on, until the agent says it is done with its tool. A failed turn
is tried again later, and a chat a restart interrupted goes on by itself. Questions, plans
and permissions are answered here too, each one kept for the report.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime, timedelta
from typing import Protocol

from pydantic import JsonValue

from nestd.approvals.models import BLOCKING, USER_ONLY, Approval, ApprovalKind
from nestd.approvals.queue import ApprovalQueue
from nestd.autopilot.answers import (
    answers,
    blocked,
    chosen,
    permission_decision,
    plan_decision,
    question_decision,
    refusal,
    stored_question,
)
from nestd.autopilot.keep_awake import KeepAwake
from nestd.autopilot.models import (
    Autopilot,
    AutopilotBudget,
    AutopilotDecision,
    AutopilotEnd,
    AutopilotReport,
)
from nestd.clock import Clock
from nestd.config.models import PermissionMode
from nestd.errors import NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    QuestionAnswer,
    QuestionRequest,
)
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import IN_FLIGHT, Session, SessionState
from nestd.sessions.store import SessionStore

logger = logging.getLogger(__name__)

KEEP_GOING_TEXT = (
    "Keep going until the whole task is done and checked. If it is, call autopilot_finished."
)
NUDGE_TEXT = "You seem stuck. Try another way, and keep going until the task is done."
RESUME_TEXT = "Your turn was cut off. Check where you were, and keep going."
RETRY_TEXT = "Your turn failed. Check where you were, and keep going."

# Turns in a row without a tool call, and stuck flags, before a run gives up.
MAX_IDLE_TURNS = 3
MAX_NUDGES = 3
# Failed turns in a row before a run gives up, and the wait before the first retry, which
# grows four times with each one.
MAX_ERRORS = 5
FIRST_RETRY = timedelta(seconds=30)
LONGEST_RETRY = timedelta(minutes=10)

# Stuck flags a nudge can help with: a long turn may be fine, and prompts are answered here.
_NUDGED = ("silent", "repeating")

ENDED_TEXT: dict[AutopilotEnd, str] = {
    "done": "Autopilot finished the task.",
    "time": "Autopilot stopped: its time ran out.",
    "weekly_cap": "Autopilot stopped at its weekly usage cap.",
    "stuck": "Autopilot stopped: the agent got stuck.",
    "errors": "Autopilot stopped: the agent kept failing.",
    "stopped": "Autopilot stopped.",
    "off": "Autopilot is off.",
}


class AutopilotHost(Protocol):
    """What Autopilot needs of the sessions."""

    async def resting(self, session_id: str) -> bool:
        """Whether nothing runs, waits in the queue or goes on by itself in the chat."""
        ...

    def worked(self, session_id: str) -> bool:
        """Whether the agent called a tool since this was last asked."""
        ...

    async def continue_chat(self, session_id: str, text: str, interrupt: bool) -> None: ...

    async def stop_turn(self, session_id: str) -> None: ...

    def in_turn(self, session_id: str) -> bool:
        """Whether a turn runs, so the agent may still write in the chat."""
        ...

    async def restore_mode(self, session: Session, run: Autopilot) -> None: ...

    async def run_ended(self, session: Session, text: str) -> None:
        """The run ended: its work goes to review and the user hears about it."""
        ...


class AutopilotRunner:
    def __init__(
        self,
        store: SessionStore,
        bus: EventBus,
        approvals: ApprovalQueue,
        clock: Clock,
        keep_awake: KeepAwake | None,
        weekly_used: Callable[[Session], Awaitable[float | None]],
        save: Callable[[str, dict[str, object]], Awaitable[Session]],
        can_push: Callable[[], bool] = lambda: False,
    ) -> None:
        """`keep_awake` is None where nothing may start a process (tests). `weekly_used` is
        how much of the weekly window the chat's engine has used, in percent; `save` stores
        and announces a session's fields; `can_push` whether the user lets agents push.
        """
        self._store = store
        self._bus = bus
        self._approvals = approvals
        self._clock = clock
        self._keep_awake = keep_awake
        self._weekly_used = weekly_used
        self._save = save
        self._can_push = can_push
        self._active: set[str] = set()
        # Reports of runs that ended during a turn; each goes in the chat when the turn ends.
        self._reports: dict[str, list[AutopilotReport]] = {}
        # Prompts come in while a tick works on the same run; neither may lose the other's.
        self._lock = asyncio.Lock()
        self.host: AutopilotHost | None = None

    async def load(self) -> None:
        self._active = set(await self._store.autopilots())
        if self._active:
            await self._hold()

    async def shutdown(self) -> None:
        for session_id in list(self._reports):
            await self.turn_ended(session_id)
        await self._release()

    def active(self, session_id: str) -> bool:
        return session_id in self._active

    async def start(
        self,
        session: Session,
        budget: AutopilotBudget,
        mode: PermissionMode,
        *,
        announce: bool = True,
    ) -> Session:
        """`mode` is the one the chat goes back to. A chat being created is announced with
        its run, so nothing is announced here (`announce`).
        """
        now = self._clock.now()
        run = Autopilot(
            started_at=now,
            until=_until(now, budget),
            weekly_cap=budget.weekly_cap,
            mode=mode,
            follows_claude_code_mode=session.follows_claude_code_mode,
        )
        async with self._lock:
            self._active.add(session.id)
            changes: dict[str, object] = {"autopilot": run}
            session = await (
                self._save(session.id, changes)
                if announce
                else self._store.update(session.id, **changes)
            )
        await self._hold()
        return session

    async def set_budget(self, session: Session, budget: AutopilotBudget) -> Session:
        run = session.autopilot
        if run is None:
            return session

        def change(current: Autopilot) -> Autopilot:
            until = _until(current.started_at, budget)
            return current.model_copy(update={"until": until, "weekly_cap": budget.weekly_cap})

        return await self._change(session.id, change) or session

    async def finished(self, session_id: str, summary: str) -> None:
        """The agent says the task is done; the run ends with its turn."""

        def change(current: Autopilot) -> Autopilot:
            return current.model_copy(update={"summary": summary})

        await self._change(session_id, change)

    async def end(self, session_id: str, how: AutopilotEnd) -> None:
        """End the run, if there is one: the chat gets its mode back, and a report, after
        what the agent still writes in a turn this leaves running or is about to stop.
        """
        host = self._require_host()
        async with self._lock:
            session = await self._store.get(session_id)
            run = session.autopilot
            self._active.discard(session_id)
            if run is None:
                return
            report = AutopilotReport(
                started_at=run.started_at,
                ended_at=self._clock.now(),
                ended=how,
                summary=run.summary,
                turns=run.turns,
                decisions=run.decisions,
            )
            session = await self._save(session_id, {"autopilot": None})
            self._reports.setdefault(session_id, []).append(report)
            if not host.in_turn(session_id):
                await self.turn_ended(session_id)
        await self._release_unused()
        await host.restore_mode(session, run)
        await host.run_ended(await self._store.get(session_id), ENDED_TEXT[how])

    async def turn_ended(self, session_id: str) -> None:
        """Put the reports waiting for this turn in the chat."""
        for report in self._reports.pop(session_id, []):
            await self._bus.publish(
                types.SESSION_AUTOPILOT_REPORT,
                {"report": report.model_dump(mode="json")},
                session_id,
            )

    # What the agent asks

    async def permission(
        self, session_id: str, request: PermissionRequest
    ) -> PermissionDecision | None:
        """None when the chat is not on Autopilot."""
        if session_id not in self._active:
            return None
        title = request.title or request.tool_name
        if await self._settle(
            session_id, title, request.tool_name, request.tool_input, request.reason
        ):
            return PermissionDecision("allow")
        return PermissionDecision("deny", refusal(can_push=self._can_push()))

    async def question(self, session_id: str, request: QuestionRequest) -> QuestionAnswer | None:
        if session_id not in self._active:
            return None
        for question in request.questions:
            await self._note(session_id, question_decision(question, self._clock.now()))
        return QuestionAnswer(answers(request))

    async def plan(self, session_id: str, request: PlanRequest) -> PlanDecision | None:
        """Approved without a mode: the chat stays as Autopilot put it."""
        if session_id not in self._active:
            return None
        await self._note(session_id, plan_decision(request.plan, self._clock.now()))
        return PlanDecision(approved=True)

    async def answer_pending(self, session_id: str) -> None:
        """Answer what already waited when the run began, or came in as it began. Cards
        only the user answers stay for the user (B159 R05).
        """
        for kind in BLOCKING:
            while answerable := [
                approval
                for approval in await self._approvals.pending_all(session_id, kind)
                if approval.payload.get(USER_ONLY) is not True
            ]:
                await self._answer(session_id, answerable[-1])

    async def _answer(self, session_id: str, approval: Approval) -> None:
        await self._approvals.resolve(approval.id, await self._resolution(session_id, approval))

    async def _resolution(self, session_id: str, approval: Approval) -> dict[str, JsonValue]:
        payload = approval.payload
        if approval.kind is ApprovalKind.QUESTION:
            raw = payload.get("questions")
            stored = [stored_question(q) for q in (raw if isinstance(raw, list) else [])]
            questions = [q for q in stored if q is not None]
            for question in questions:
                await self._note(session_id, question_decision(question, self._clock.now()))
            return {"answers": {q.question: chosen(q) for q in questions}}
        if approval.kind is ApprovalKind.PLAN:
            plan = payload.get("plan")
            decision = plan_decision(plan if isinstance(plan, str) else "", self._clock.now())
            await self._note(session_id, decision)
            return {"decision": "approve", "mode": "acceptEdits"}
        tool = str(payload.get("tool"))
        tool_input = payload.get("input")
        title = str(payload.get("title") or tool)
        reason = payload.get("reason")
        if await self._settle(
            session_id,
            title,
            tool,
            tool_input if isinstance(tool_input, dict) else {},
            reason if isinstance(reason, str) else None,
        ):
            return {"behavior": "allow", "message": None, "always": False}
        return {
            "behavior": "deny",
            "message": refusal(can_push=self._can_push()),
            "always": False,
        }

    async def _settle(
        self,
        session_id: str,
        title: str,
        tool: str,
        tool_input: Mapping[str, object],
        reason: str | None,
    ) -> bool:
        """Note a permission's answer, and say whether it is allowed."""
        can_push = self._can_push()
        denied = blocked(tool, tool_input, can_push=can_push)
        told = refusal(can_push=can_push) if denied else reason
        decision = permission_decision(title, denied=denied, reason=told, at=self._clock.now())
        await self._note(session_id, decision)
        return not denied

    async def _note(self, session_id: str, decision: AutopilotDecision) -> None:
        """On the run for its report, and in the chat at the moment it happened."""

        def change(current: Autopilot) -> Autopilot:
            return current.model_copy(update={"decisions": [*current.decisions, decision]})

        if await self._change(session_id, change) is not None:
            await self._bus.publish(
                types.SESSION_AUTOPILOT_DECISION,
                {"decision": decision.model_dump(mode="json")},
                session_id,
            )

    # The ticks

    async def tick(self) -> None:
        # A closed or archived chat's turn ends without saying so.
        for session_id in list(self._reports):
            if not self._require_host().in_turn(session_id):
                await self.turn_ended(session_id)
        for session_id in list(self._active):
            try:
                await self._step(session_id, self._clock.now())
            except SessionNotFoundError:
                self._active.discard(session_id)
                await self._release_unused()
            except Exception as error:
                logger.warning("autopilot of session %s failed (%s)", session_id, error)

    async def _step(self, session_id: str, now: datetime) -> None:
        session = await self._store.get(session_id)
        run = session.autopilot
        if run is None:
            self._active.discard(session_id)
            return
        if session.state is SessionState.CLOSED or session.archived_at is not None:
            await self.end(session_id, "off")
            return
        over = await self._over_budget(session, run, now)
        if over is not None:
            await self.end(session_id, over)
            await self._require_host().stop_turn(session_id)
        elif session.state in IN_FLIGHT:
            await self.answer_pending(session_id)
            await self._watch(session, run)
        elif session.limit_pause is None and await self._require_host().resting(session_id):
            await self._go_on(session, run, now)

    async def _over_budget(
        self, session: Session, run: Autopilot, now: datetime
    ) -> AutopilotEnd | None:
        if run.until is not None and now >= run.until:
            return "time"
        if run.weekly_cap is None:
            return None
        used = await self._weekly_used(session)
        return "weekly_cap" if used is not None and used >= run.weekly_cap else None

    async def _watch(self, session: Session, run: Autopilot) -> None:
        flag = session.stuck
        if flag is None or flag.reason not in _NUDGED or run.nudged_since == flag.since:
            return
        if run.nudges >= MAX_NUDGES:
            await self.end(session.id, "stuck")
            await self._require_host().stop_turn(session.id)
            return
        since = flag.since

        def change(current: Autopilot) -> Autopilot:
            return current.model_copy(update={"nudges": current.nudges + 1, "nudged_since": since})

        await self._change(session.id, change)
        await self._send(session.id, NUDGE_TEXT, interrupt=True)

    async def _go_on(self, session: Session, run: Autopilot, now: datetime) -> None:
        if run.summary is not None:
            await self.end(session.id, "done")
        elif session.state is SessionState.FAILED:
            await self._retry(session.id, run, now)
        elif session.state is SessionState.INTERRUPTED:
            await self._send(session.id, RESUME_TEXT)
        else:
            await self._keep_going(session.id, run)

    async def _keep_going(self, session_id: str, run: Autopilot) -> None:
        worked = self._require_host().worked(session_id)
        idle_turns = 0 if worked else run.idle_turns + 1
        if idle_turns > MAX_IDLE_TURNS:
            await self.end(session_id, "stuck")
            return

        def change(current: Autopilot) -> Autopilot:
            nudges = 0 if worked else current.nudges
            return current.model_copy(
                update={"idle_turns": idle_turns, "errors": 0, "nudges": nudges}
            )

        await self._change(session_id, change)
        await self._send(session_id, KEEP_GOING_TEXT)

    async def _retry(self, session_id: str, run: Autopilot, now: datetime) -> None:
        if run.retry_at is None:
            await self._failed(session_id, run, now)
        elif now >= run.retry_at:

            def change(current: Autopilot) -> Autopilot:
                return current.model_copy(update={"retry_at": None})

            await self._change(session_id, change)
            await self._send(session_id, RETRY_TEXT)

    async def _failed(self, session_id: str, run: Autopilot, now: datetime) -> None:
        errors = run.errors + 1
        if errors > MAX_ERRORS:
            await self.end(session_id, "errors")
            return
        retry_at = now + min(FIRST_RETRY * 4 ** (errors - 1), LONGEST_RETRY)

        def change(current: Autopilot) -> Autopilot:
            return current.model_copy(update={"errors": errors, "retry_at": retry_at})

        await self._change(session_id, change)

    async def _send(self, session_id: str, text: str, interrupt: bool = False) -> None:
        def change(current: Autopilot) -> Autopilot:
            return current.model_copy(update={"turns": current.turns + 1})

        try:
            await self._require_host().continue_chat(session_id, text, interrupt)
        except NestError as error:
            logger.warning("autopilot could not go on in %s (%s)", session_id, error)
            session = await self._store.get(session_id)
            if session.autopilot is not None:
                await self._failed(session_id, session.autopilot, self._clock.now())
            return
        await self._change(session_id, change)

    async def _change(
        self, session_id: str, change: Callable[[Autopilot], Autopilot]
    ) -> Session | None:
        async with self._lock:
            session = await self._store.get(session_id)
            if session.autopilot is None:
                return None
            return await self._save(session_id, {"autopilot": change(session.autopilot)})

    async def _hold(self) -> None:
        if self._keep_awake is not None:
            await self._keep_awake.hold()

    async def _release(self) -> None:
        if self._keep_awake is not None:
            await self._keep_awake.release()

    async def _release_unused(self) -> None:
        if not self._active:
            await self._release()

    def _require_host(self) -> AutopilotHost:
        host = self.host
        assert host is not None  # noqa: S101 (set when the sessions are built)
        return host


def _until(start: datetime, budget: AutopilotBudget) -> datetime | None:
    minutes = budget.stop_after_minutes
    return None if minutes is None else start + timedelta(minutes=minutes)
