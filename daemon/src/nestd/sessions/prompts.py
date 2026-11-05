"""An agent run's permission prompts and questions, held in the approval queue."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import get_args

from pydantic import JsonValue

from nestd.approvals.models import Approval, ApprovalKind, ApprovalStatus
from nestd.approvals.queue import ApprovalQueue
from nestd.autopilot.runner import AutopilotRunner
from nestd.config.models import PermissionMode, PlanApprovalMode
from nestd.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    Question,
    QuestionAnswer,
    QuestionRequest,
)
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import PixieCalls

# Told whether the session still has a run waiting on the user, after each change.
type WaitingCallback = Callable[[str, bool], Awaitable[None]]
# Persists and announces a new permission mode for the session.
type ModeCallback = Callable[[str, PermissionMode], Awaitable[None]]

DEFAULT_QUESTION_NOTICE = "The agent has a question."
PLAN_NOTICE = "The plan is ready for review."
# An approved plan continues with edits allowed, as in Claude Code (D032), unless the user
# chose another of PLAN_MODES.
PLAN_APPROVED_MODE: PermissionMode = "acceptEdits"
PLAN_MODES: dict[str, PermissionMode] = {mode: mode for mode in get_args(PlanApprovalMode)}
KEEP_PLANNING = "Keep planning"
# Calls nest no deeper than a team's leader calling its members; a bound for safety.
_MAX_CALL_DEPTH = 8


def keep_planning_message(note: str | None) -> str:
    """What the agent hears when the user wants more planning, with the user's note."""
    return f"{KEEP_PLANNING}: {note}" if note else f"{KEEP_PLANNING}."


class SessionPrompts:
    """The approval handler of one session's agent run."""

    def __init__(
        self,
        session_id: str,
        queue: ApprovalQueue,
        store: SessionStore,
        on_waiting: WaitingCallback,
        on_mode: ModeCallback,
        calls: PixieCalls | None = None,
        autopilot: AutopilotRunner | None = None,
    ) -> None:
        """`calls` names the pixie call an approval comes from (B114); `autopilot` answers
        for a chat on Autopilot, and for the pixies it called.
        """
        self._autopilot = autopilot
        self._calls = calls
        self._session_id = session_id
        self._queue = queue
        self._store = store
        self._on_waiting = on_waiting
        self._on_mode = on_mode
        # Two answers at once must not both read the old rules and keep only one (PL-04).
        self._rules = asyncio.Lock()

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        session = await self._store.get(self._session_id)
        if request.tool_name in session.allowed_tools:
            return PermissionDecision("allow")
        if session.called_by is not None:
            # What the caller allows for good, its subagents may do (B112).
            caller = await self._store.get((await self._chain())[-1])
            if request.tool_name in caller.allowed_tools:
                return PermissionDecision("allow")
        if self._autopilot is not None:
            auto = await self._autopilot.permission(await self._owner(), request)
            if auto is not None:
                return auto
        approval = await self._wait(
            ApprovalKind.PERMISSION,
            {
                "tool": request.tool_name,
                "input": request.tool_input,
                "title": request.title,
                "reason": request.reason,
                "always_rule": request.always_rule,
            },
            request.title or f"Allow {request.tool_name}?",
            request.agent_id,
        )
        resolution = approval.resolution or {}
        if approval.status is not ApprovalStatus.RESOLVED:
            return PermissionDecision("deny", _text(resolution.get("reason")))
        if resolution.get("behavior") != "allow":
            return PermissionDecision("deny", _text(resolution.get("message")))
        always = resolution.get("always") is True
        if always and request.always_rule is None:
            # Nothing suggested: the tool is allowed by name for the rest of the session.
            # Otherwise the engine applies the rule it suggested, wherever it keeps it.
            await self._allow_always(request.tool_name)
        return PermissionDecision("allow", _text(resolution.get("message")), always)

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        if self._autopilot is not None:
            auto = await self._autopilot.question(await self._owner(), request)
            if auto is not None:
                return auto
        approval = await self._wait(
            ApprovalKind.QUESTION,
            {
                "tool_use_id": request.tool_use_id,
                "questions": [_question(q) for q in request.questions],
            },
            request.questions[0].question if request.questions else DEFAULT_QUESTION_NOTICE,
            request.agent_id,
        )
        resolution = approval.resolution or {}
        answers = resolution.get("answers")
        if approval.status is ApprovalStatus.RESOLVED and isinstance(answers, dict):
            return QuestionAnswer({question: str(text) for question, text in answers.items()})
        return QuestionAnswer(
            None, _text(resolution.get("message")) or _text(resolution.get("reason"))
        )

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        if self._autopilot is not None:
            auto = await self._autopilot.plan(await self._owner(), request)
            if auto is not None:
                return auto
        approval = await self._wait(
            ApprovalKind.PLAN,
            {"plan": request.plan, "tool_use_id": request.tool_use_id},
            PLAN_NOTICE,
            request.agent_id,
        )
        resolution = approval.resolution or {}
        if approval.status is not ApprovalStatus.RESOLVED:
            return PlanDecision(approved=False, message=_text(resolution.get("reason")))
        if resolution.get("decision") != "approve":
            return PlanDecision(
                approved=False, message=keep_planning_message(_text(resolution.get("message")))
            )
        chosen = resolution.get("mode")
        mode = PLAN_MODES.get(chosen if isinstance(chosen, str) else "", PLAN_APPROVED_MODE)
        await self._on_mode(self._session_id, mode)
        return PlanDecision(approved=True, mode=mode)

    async def _wait(
        self,
        kind: ApprovalKind,
        payload: dict[str, JsonValue],
        notice: str,
        agent_id: str | None,
    ) -> Approval:
        """A called pixie's item is its caller's, listed and notified as the caller's own,
        as a subagent's is (B112); its own run waits on it, and both show waiting. An item
        from inside a pixie call names the call (B114).
        """
        *called, owner = await self._chain()
        sessions = dict.fromkeys((self._session_id, owner))
        agent_ids = ([agent_id] if agent_id is not None else []) + called
        if self._calls is not None and agent_ids:
            origin = await self._calls.origin(owner, agent_ids)
            if origin is not None:
                payload = {**payload, "call": origin.call, "agent": origin.agent}

        async def on_waiting(_waiting: bool) -> None:
            for session_id in sessions:
                await self._on_waiting(session_id, self._queue.waiting(session_id))

        return await self._queue.wait(
            owner, kind, payload, notice, on_waiting, run_session_id=self._session_id
        )

    async def _owner(self) -> str:
        return (await self._chain())[-1]

    async def _chain(self) -> list[str]:
        """The session, then each chat that called it, ending with the chat the calls
        began in (the session itself unless a pixie called it).
        """
        session = await self._store.get(self._session_id)
        chain = [session.id]
        for _ in range(_MAX_CALL_DEPTH):
            if session.called_by is None:
                break
            session = await self._store.get(session.called_by)
            chain.append(session.id)
        return chain

    async def _allow_always(self, tool_name: str) -> None:
        async with self._rules:
            session = await self._store.get(self._session_id)
            if tool_name not in session.allowed_tools:
                await self._store.update(
                    self._session_id, allowed_tools=[*session.allowed_tools, tool_name]
                )


def _question(question: Question) -> JsonValue:
    return {
        "question": question.question,
        "header": question.header,
        "multi_select": question.multi_select,
        "options": [
            {"label": o.label, "description": o.description, "recommended": o.recommended}
            for o in question.options
        ],
    }


def _text(value: JsonValue) -> str | None:
    return value if isinstance(value, str) else None
