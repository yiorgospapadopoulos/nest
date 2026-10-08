"""An agent run's permission prompts and questions, held in the approval queue."""

import asyncio
from collections.abc import Awaitable, Callable

from pydantic import JsonValue

from harness.approvals.models import Approval, ApprovalKind, ApprovalStatus
from harness.approvals.queue import ApprovalQueue
from harness.config.models import PermissionMode
from harness.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    Question,
    QuestionAnswer,
    QuestionRequest,
)
from harness.sessions.store import SessionStore

# Told whether the session still has a run waiting on the user, after each change.
type WaitingCallback = Callable[[str, bool], Awaitable[None]]
# Persists and announces a new permission mode for the session.
type ModeCallback = Callable[[str, PermissionMode], Awaitable[None]]

DEFAULT_QUESTION_NOTICE = "The agent has a question."
PLAN_NOTICE = "The plan is ready for review."
# An approved plan continues with edits allowed, as in Claude Code (D032).
PLAN_APPROVED_MODE: PermissionMode = "acceptEdits"
KEEP_PLANNING = "Keep planning"


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
    ) -> None:
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
        approval = await self._wait(
            ApprovalKind.PERMISSION,
            {
                "tool": request.tool_name,
                "input": request.tool_input,
                "title": request.title,
                "reason": request.reason,
            },
            request.title or f"Allow {request.tool_name}?",
        )
        resolution = approval.resolution or {}
        if approval.status is not ApprovalStatus.RESOLVED:
            return PermissionDecision("deny", _text(resolution.get("reason")))
        if resolution.get("behavior") != "allow":
            return PermissionDecision("deny", _text(resolution.get("message")))
        if resolution.get("always") is True:
            await self._allow_always(request.tool_name)
        return PermissionDecision("allow", _text(resolution.get("message")))

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        approval = await self._wait(
            ApprovalKind.QUESTION,
            {
                "tool_use_id": request.tool_use_id,
                "questions": [_question(q) for q in request.questions],
            },
            request.questions[0].question if request.questions else DEFAULT_QUESTION_NOTICE,
        )
        resolution = approval.resolution or {}
        answers = resolution.get("answers")
        if approval.status is ApprovalStatus.RESOLVED and isinstance(answers, dict):
            return QuestionAnswer({question: str(text) for question, text in answers.items()})
        return QuestionAnswer(
            None, _text(resolution.get("message")) or _text(resolution.get("reason"))
        )

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        approval = await self._wait(
            ApprovalKind.PLAN,
            {"plan": request.plan, "tool_use_id": request.tool_use_id},
            PLAN_NOTICE,
        )
        resolution = approval.resolution or {}
        if approval.status is not ApprovalStatus.RESOLVED:
            return PlanDecision(approved=False, message=_text(resolution.get("reason")))
        if resolution.get("decision") != "approve":
            return PlanDecision(
                approved=False, message=keep_planning_message(_text(resolution.get("message")))
            )
        await self._on_mode(self._session_id, PLAN_APPROVED_MODE)
        return PlanDecision(approved=True, mode=PLAN_APPROVED_MODE)

    async def _wait(
        self, kind: ApprovalKind, payload: dict[str, JsonValue], notice: str
    ) -> Approval:
        async def on_waiting(waiting: bool) -> None:
            await self._on_waiting(self._session_id, waiting)

        return await self._queue.wait(self._session_id, kind, payload, notice, on_waiting)

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
