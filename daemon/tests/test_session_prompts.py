import asyncio

import pytest

from harness.approvals.models import Approval, ApprovalKind, ApprovalStatus
from harness.approvals.queue import ApprovalQueue
from harness.approvals.store import ApprovalStore
from harness.config.models import PermissionMode
from harness.events.bus import EventBus
from harness.notifications.notifier import Notifier
from harness.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    Question,
    QuestionAnswer,
    QuestionOption,
    QuestionRequest,
)
from harness.sessions.prompts import SessionPrompts
from harness.sessions.store import SessionStore
from harness.storage.db import Database
from tests.async_support import until
from tests.fakes import FakeClock
from tests.test_session_store import new_session

QUESTIONS = QuestionRequest(
    tool_use_id="toolu_q",
    questions=(
        Question(
            "Which structure?",
            "Data",
            (QuestionOption("DAG", "with deps", recommended=True), QuestionOption("Tree")),
            False,
        ),
    ),
)


class Env:
    def __init__(self, db: Database, clock: FakeClock) -> None:
        bus = EventBus(db, clock)
        self.store = SessionStore(db, clock)
        self.queue = ApprovalQueue(ApprovalStore(db, clock), bus, Notifier(bus))
        self.waiting: list[tuple[str, bool]] = []
        self.modes: list[tuple[str, PermissionMode]] = []

    async def prompts(self) -> SessionPrompts:
        session = await self.store.create(new_session())
        return SessionPrompts(session.id, self.queue, self.store, self.on_waiting, self.on_mode)

    async def on_waiting(self, session_id: str, waiting: bool) -> None:
        self.waiting.append((session_id, waiting))

    async def on_mode(self, session_id: str, mode: PermissionMode) -> None:
        self.modes.append((session_id, mode))

    async def pending(self) -> Approval:
        async def created() -> bool:
            return bool(await self.queue.list_approvals(ApprovalStatus.PENDING))

        await until(created)
        (approval,) = await self.queue.list_approvals(ApprovalStatus.PENDING)
        return approval


@pytest.fixture
def env(db: Database, clock: FakeClock) -> Env:
    return Env(db, clock)


async def test_a_permission_becomes_an_approval_item(env: Env) -> None:
    prompts = await env.prompts()
    request = PermissionRequest("Bash", {"command": "ls"}, "Claude wants to run ls")

    deciding = asyncio.ensure_future(prompts.decide(request))
    item = await env.pending()
    await env.queue.resolve(item.id, {"behavior": "deny", "message": "not now", "always": False})

    assert await deciding == PermissionDecision("deny", "not now")
    assert item.kind is ApprovalKind.PERMISSION
    assert item.payload == {
        "tool": "Bash",
        "input": {"command": "ls"},
        "title": "Claude wants to run ls",
    }
    session_id = item.session_id
    assert env.waiting == [(session_id, True), (session_id, False)]


async def test_always_allows_the_tool_for_the_rest_of_the_session(env: Env) -> None:
    prompts = await env.prompts()

    first = asyncio.ensure_future(prompts.decide(PermissionRequest("Edit", {"file": "a"})))
    item = await env.pending()
    await env.queue.resolve(item.id, {"behavior": "allow", "message": None, "always": True})
    decision = await first
    later = await prompts.decide(PermissionRequest("Edit", {"file": "b"}))

    assert decision == PermissionDecision("allow")
    assert later == PermissionDecision("allow")
    assert (await env.store.get(item.session_id)).allowed_tools == ["Edit"]
    assert len(await env.queue.list_approvals()) == 1


async def test_a_permission_without_a_title_gets_a_notice(env: Env) -> None:
    prompts = await env.prompts()

    deciding = asyncio.ensure_future(prompts.decide(PermissionRequest("Write", {})))
    item = await env.pending()
    await env.queue.expire(item.session_id, (ApprovalKind.PERMISSION,), "interrupted")

    assert await deciding == PermissionDecision("deny", "interrupted")
    assert item.payload["title"] is None


async def test_a_question_becomes_an_approval_item(env: Env) -> None:
    prompts = await env.prompts()

    asking = asyncio.ensure_future(prompts.ask(QUESTIONS))
    item = await env.pending()
    await env.queue.resolve(item.id, {"answers": {"Which structure?": "DAG"}})

    assert await asking == QuestionAnswer({"Which structure?": "DAG"})
    assert item.kind is ApprovalKind.QUESTION
    assert item.payload == {
        "tool_use_id": "toolu_q",
        "questions": [
            {
                "question": "Which structure?",
                "header": "Data",
                "multi_select": False,
                "options": [
                    {"label": "DAG", "description": "with deps", "recommended": True},
                    {"label": "Tree", "description": None, "recommended": False},
                ],
            }
        ],
    }


@pytest.mark.parametrize(
    ("resolution", "message"),
    [({"dismissed": True, "message": "later"}, "later"), ({"dismissed": True}, None)],
)
async def test_a_dismissed_question(
    env: Env, resolution: dict[str, object], message: str | None
) -> None:
    prompts = await env.prompts()

    asking = asyncio.ensure_future(prompts.ask(QUESTIONS))
    item = await env.pending()
    await env.queue.resolve(item.id, dict(resolution))  # pyright: ignore[reportArgumentType]

    assert await asking == QuestionAnswer(None, message)


async def test_an_expired_question_tells_the_agent_why(env: Env) -> None:
    prompts = await env.prompts()

    asking = asyncio.ensure_future(prompts.ask(QuestionRequest(questions=())))
    item = await env.pending()
    await env.queue.expire(item.session_id, (ApprovalKind.QUESTION,), "the session was closed")

    assert await asking == QuestionAnswer(None, "the session was closed")


async def test_parallel_always_answers_add_the_rule_once(env: Env) -> None:
    prompts = await env.prompts()
    first = asyncio.ensure_future(prompts.decide(PermissionRequest("Edit", {"file": "a"})))
    second = asyncio.ensure_future(prompts.decide(PermissionRequest("Edit", {"file": "b"})))

    async def both() -> bool:
        return len(await env.queue.list_approvals(ApprovalStatus.PENDING)) == 2

    await until(both)
    items = await env.queue.list_approvals(ApprovalStatus.PENDING)
    for item in items:
        await env.queue.resolve(item.id, {"behavior": "allow", "always": True})
    await asyncio.gather(first, second)

    assert (await env.store.get(items[0].session_id)).allowed_tools == ["Edit"]


async def test_an_approved_plan_continues_with_edits_allowed(env: Env) -> None:
    prompts = await env.prompts()

    reviewing = asyncio.ensure_future(prompts.review_plan(PlanRequest("# Plan\n- a", "toolu_p")))
    item = await env.pending()
    await env.queue.resolve(item.id, {"decision": "approve"})

    assert await reviewing == PlanDecision(approved=True, mode="acceptEdits")
    assert item.kind is ApprovalKind.PLAN
    assert item.payload == {"plan": "# Plan\n- a", "tool_use_id": "toolu_p"}
    assert env.modes == [(item.session_id, "acceptEdits")]
    assert env.waiting == [(item.session_id, True), (item.session_id, False)]


@pytest.mark.parametrize(
    ("note", "message"),
    [("split step 2", "Keep planning: split step 2"), (None, "Keep planning.")],
)
async def test_keep_planning_tells_the_agent_with_the_note(
    env: Env, note: str | None, message: str
) -> None:
    prompts = await env.prompts()

    reviewing = asyncio.ensure_future(prompts.review_plan(PlanRequest("plan")))
    item = await env.pending()
    await env.queue.resolve(item.id, {"decision": "keep_planning", "message": note})

    assert await reviewing == PlanDecision(approved=False, message=message)
    assert env.modes == []


async def test_an_expired_plan_tells_the_agent_why(env: Env) -> None:
    prompts = await env.prompts()

    reviewing = asyncio.ensure_future(prompts.review_plan(PlanRequest("plan")))
    item = await env.pending()
    await env.queue.expire(item.session_id, (ApprovalKind.PLAN,), "interrupted by the user")

    assert await reviewing == PlanDecision(approved=False, message="interrupted by the user")
