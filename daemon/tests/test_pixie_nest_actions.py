"""A pixie's message, start and answer tools, its limits, cards and activity log (B41)."""

import asyncio
from datetime import timedelta

import pytest

from nestd.approvals.models import ApprovalKind, ApprovalStatus
from nestd.context import AppContext
from nestd.events import types
from nestd.pixies.models import UpdatePixie
from nestd.providers.base import Question, QuestionOption, QuestionRequest
from nestd.sessions.models import CreateSession, Session, SessionState
from tests.async_support import until
from tests.fake_provider import FakeProvider, FakeRun, ask, edit, hang, plan, question, reply
from tests.fakes import FakeClock
from tests.pixie_nest_support import Boss, ctx, idle, make_boss, provider, user_chat

__all__ = ["ctx", "provider"]


async def senders(ctx: AppContext, session_id: str) -> list[tuple[object, object]]:
    return [
        (e.payload["text"], e.payload.get("from_pixie"))
        for e in await ctx.bus.session_events(session_id)
        if e.type == types.SESSION_USER_MESSAGE
    ]


async def activity(boss: Boss) -> list[tuple[str, str | None, str]]:
    entries = await boss.ctx.pixies.activity(boss.pixie.id)
    return [(a.tool, a.session_id, a.summary) for a in entries]


@pytest.mark.parametrize(
    ("tool", "level", "args"),
    [
        ("send_message", "Message", {"id": "x", "text": "hi"}),
        ("nudge", "Message", {"id": "x", "reason": "looping"}),
        ("interrupt", "Message", {"id": "x"}),
        ("start_session", "Start", {"project": "web", "prompt": "go"}),
        ("close_session", "Start", {"id": "x"}),
        ("answer_permission", "Answer", {"approval_id": "x", "allow": True}),
        ("answer_question", "Answer", {"approval_id": "x", "answers": {}}),
        ("approve_plan", "Answer", {"approval_id": "x"}),
        ("keep_planning", "Answer", {"approval_id": "x", "feedback": "more"}),
    ],
)
async def test_tools_above_its_autonomy_are_refused(
    ctx: AppContext, provider: FakeProvider, tool: str, level: str, args: dict[str, object]
) -> None:
    boss = await make_boss(ctx, provider)

    refusal = await boss.refused(tool, **args)  # type: ignore[arg-type]

    assert refusal == (
        f"{tool} needs autonomy {level} or higher; Boss is at Observe. The user can raise it"
        " in Boss's details."
    )
    assert await activity(boss) == []


async def test_a_lowered_autonomy_applies_to_the_open_run(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="message")
    chat = await user_chat(ctx, provider)
    await ctx.pixies.update(boss.pixie.id, UpdatePixie(autonomy="observe"))

    refusal = await boss.refused("send_message", id=chat.id, text="hi")

    assert refusal.startswith("send_message needs autonomy Message or higher")


async def test_send_message_reaches_the_chat_as_the_pixies(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="message")
    chat = await user_chat(ctx, provider)
    provider.script(reply("on it"))

    sent = await boss.call("send_message", id=chat.id, text="Also update the docs")
    await idle(ctx, chat.id)
    empty = await boss.refused("send_message", id=chat.id, text="  ")
    pixie_chat = await boss.refused("send_message", id=boss.chat_id, text="hi")

    too_long = await boss.refused("send_message", id=chat.id, text="x" * 20_001)

    assert sent == "Sent."
    assert too_long == "text is too long: at most 20000 characters."
    assert (await senders(ctx, chat.id))[-1] == ("Also update the docs", boss.pixie.id)
    assert empty == "text is required."
    assert pixie_chat == "That is a pixie's chat; pixies never act on pixie chats."
    assert await activity(boss) == [("send_message", chat.id, "Sent: Also update the docs")]


async def test_a_message_to_a_busy_chat_is_queued(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider, autonomy="message")
    provider.script(hang())
    busy = await ctx.sessions.create(CreateSession(repo="web", prompt="Long", mode="worktree"))
    await until(lambda: ctx.sessions.busy(busy.id))

    sent = await boss.call("send_message", id=busy.id, text="when you can")

    assert sent == "Queued: the chat is busy, so the message starts its next turn."


async def test_nudge_and_interrupt_stop_the_turn(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider, autonomy="message")
    started = asyncio.Event()

    async def long(run: FakeRun) -> None:
        started.set()
        await run.interrupted.wait()
        await reply("stopped")(run)

    provider.script(long, long, reply("trying again"))
    chat = await ctx.sessions.create(CreateSession(repo="web", prompt="Loop", mode="worktree"))
    await started.wait()
    started.clear()

    nudged = await boss.call("nudge", id=chat.id, reason="it repeats the same test")
    await started.wait()
    stopped = await boss.call("interrupt", id=chat.id)
    await ctx.sessions.get(chat.id)
    session = await until_state(ctx, chat.id, SessionState.INTERRUPTED)
    nothing = await boss.refused("interrupt", id=chat.id)

    assert nudged == "Nudged: the turn stops and your message starts the next one."
    assert (await senders(ctx, chat.id))[1] == (
        "You seem stuck: it repeats the same test. Step back and try a different approach.",
        boss.pixie.id,
    )
    assert stopped == "Stopped the turn."
    assert session.state is SessionState.INTERRUPTED
    assert nothing == f"session {chat.id!r} has no turn in progress"
    assert [entry[0] for entry in await activity(boss)] == ["interrupt", "nudge"]


async def until_state(ctx: AppContext, session_id: str, state: SessionState) -> Session:
    async def reached() -> bool:
        return (await ctx.sessions.get(session_id)).state is state

    await until(reached)
    return await ctx.sessions.get(session_id)


async def test_start_session_starts_a_reviewed_chat_in_its_own_worktree(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="start", permission_mode="acceptEdits")
    provider.script(reply("files listed"))

    started = await boss.call("start_session", project="web", prompt="List the files")
    (session,) = await ctx.sessions.list_sessions("web")
    session = await idle(ctx, session.id)
    run = provider.runs[-1]

    assert started == (
        f'Started chat {session.id} "List the files" in web, in its own worktree, in'
        " acceptEdits mode. You get one message when the chats you start in this turn have"
        " finished."
    )
    assert ctx.settings.agents.default_mode == "in_place"
    assert session.mode == "worktree"
    assert session.worktree_path is not None
    assert session.started_by_pixie == boss.pixie.id
    assert session.pixie_batch is not None
    assert session.pixie_batch.startswith(boss.chat_id)
    assert session.permission_mode == "acceptEdits"
    assert run.spec.permission_mode == "acceptEdits"
    assert (await senders(ctx, session.id))[0] == ("List the files", boss.pixie.id)
    assert await boss.cards() == [{"kind": "session", "session_id": session.id}]
    assert await activity(boss) == [
        ("start_session", session.id, 'Started "List the files" in web')
    ]


async def test_start_session_checks_project_mode_and_arguments(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="start")
    folder = ctx.paths.data_dir.parent / "notes"
    folder.mkdir()
    await ctx.repos.register(folder)

    unknown = await boss.refused("start_session", project="missing", prompt="go")
    looser = await boss.refused(
        "start_session", project="web", prompt="go", permission_mode="acceptEdits"
    )
    unknown_mode = await boss.refused(
        "start_session", project="web", prompt="go", permission_mode="yolo"
    )
    plain = await boss.refused("start_session", project="notes", prompt="go")
    no_prompt = await boss.refused("start_session", project="web", prompt=" ")
    bad_effort = await boss.refused("start_session", project="web", prompt="go", effort="lots")

    assert unknown == "unknown repo 'missing'"
    assert looser == (
        "acceptEdits is looser than your own permission mode (default); a chat you start can"
        " use plan or default."
    )
    assert unknown_mode == (
        "permission_mode must be one of: plan, default, acceptEdits, auto, bypassPermissions."
    )
    assert plain == "notes is not a git repository, so a chat cannot get its own worktree"
    assert no_prompt == "prompt is required."
    assert bad_effort.startswith("effort must be one of: ")
    assert await ctx.sessions.list_sessions() == []


async def test_a_stricter_mode_can_be_chosen(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider, autonomy="start", permission_mode="auto")
    provider.script(reply("planned"))

    await boss.call("start_session", project="web", prompt="Plan it", permission_mode="plan")
    (session,) = await ctx.sessions.list_sessions("web")

    assert session.permission_mode == "plan"


async def test_the_running_limit(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider, autonomy="start", max_running=1)
    provider.script(hang())

    await boss.call("start_session", project="web", prompt="Long one")
    refusal = await boss.refused("start_session", project="web", prompt="Another")
    (first,) = await ctx.sessions.list_sessions("web")
    provider.script(reply("next"))
    await ctx.sessions.interrupt(first.id)
    await until_state(ctx, first.id, SessionState.INTERRUPTED)
    again = await boss.call("start_session", project="api", prompt="Another")

    assert refusal == (
        "You already have 1 chat you started running, your limit. Wait until one finishes,"
        " or ask the user to raise the limit."
    )
    assert again.startswith("Started chat")


async def test_the_daily_limit_resets_at_local_midnight(
    ctx: AppContext, provider: FakeProvider, clock: FakeClock
) -> None:
    boss = await make_boss(ctx, provider, autonomy="start", max_per_day=2, max_running=5)
    provider.script(reply("one"), reply("two"), reply("three"))

    await boss.call("start_session", project="web", prompt="One")
    await boss.call("start_session", project="web", prompt="Two")
    refusal = await boss.refused("start_session", project="web", prompt="Three")
    clock.advance(timedelta(hours=12))
    tomorrow = await boss.call("start_session", project="web", prompt="Three")

    assert refusal == (
        "You already started 2 chats today, your limit. Try again tomorrow, or ask the user"
        " to raise the limit."
    )
    assert tomorrow.startswith("Started chat")


async def test_close_session_closes_only_its_own_chats(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="start")
    users = await user_chat(ctx, provider)
    provider.script(reply("nothing to do"), edit({"notes.md": "hi\n"}, reply("wrote")))
    await boss.call("start_session", project="web", prompt="Look around")
    await boss.call("start_session", project="api", prompt="Write notes")
    clean, worked = [s for s in await ctx.sessions.list_sessions() if s.started_by_pixie]
    clean, worked = sorted((clean, worked), key=lambda s: s.repo, reverse=True)
    clean, worked = await idle(ctx, clean.id), await idle(ctx, worked.id)

    not_mine = await boss.refused("close_session", id=users.id)
    removed = await boss.call("close_session", id=clean.id)
    kept = await boss.call("close_session", id=worked.id)
    twice = await boss.refused("close_session", id=clean.id)

    assert not_mine == "You can only do that in chats you started."
    assert removed == "Closed the chat and removed its worktree, which held no work."
    assert kept == "Closed the chat. Its worktree holds work, so it stays for the user."
    assert clean.worktree_path is not None
    assert not clean.worktree_path.exists()
    assert worked.worktree_path is not None
    assert worked.worktree_path.exists()
    assert (await ctx.sessions.get(clean.id)).state is SessionState.CLOSED
    assert twice == f"session {clean.id!r} is closed"
    assert [a[:2] for a in await activity(boss)] == [
        ("close_session", worked.id),
        ("close_session", clean.id),
        ("start_session", worked.id),
        ("start_session", clean.id),
    ]


def _db_question() -> QuestionRequest:
    return QuestionRequest(
        questions=(
            Question(
                question="Which database?",
                header="DB",
                options=(QuestionOption(label="Postgres"), QuestionOption(label="SQLite")),
                multi_select=False,
            ),
        )
    )


async def pending(ctx: AppContext, session_id: str, kind: ApprovalKind) -> str:
    async def asked() -> bool:
        return await ctx.approvals.pending(session_id, kind) is not None

    await until(asked)
    approval = await ctx.approvals.pending(session_id, kind)
    assert approval is not None
    return approval.id


async def run_of(ctx: AppContext, provider: FakeProvider, session_id: str) -> FakeRun:
    cwd = (await ctx.sessions.get(session_id)).cwd
    return next(run for run in provider.runs if run.spec.cwd == cwd)


async def started_chat(boss: Boss, *turns: object) -> Session:
    boss.provider.script(*turns)  # type: ignore[arg-type]
    await boss.call("start_session", project="web", prompt="Do it")
    return next(
        s for s in await boss.ctx.sessions.list_sessions("web") if s.started_by_pixie is not None
    )


async def test_answers_reach_the_chats_it_started(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider, autonomy="answer", permission_mode="acceptEdits")
    chat = await started_chat(
        boss, ask("Bash", ask("Write", question(_db_question(), plan("1. do", reply("done")))))
    )

    allowed = await boss.call(
        "answer_permission",
        approval_id=await pending(ctx, chat.id, ApprovalKind.PERMISSION),
        allow=True,
    )
    second = await pending(ctx, chat.id, ApprovalKind.PERMISSION)
    denied = await boss.call("answer_permission", approval_id=second, allow=False, message="no")
    answered = await boss.call(
        "answer_question",
        approval_id=await pending(ctx, chat.id, ApprovalKind.QUESTION),
        answers={"Which database?": "SQLite"},
    )
    approved = await boss.call(
        "approve_plan", approval_id=await pending(ctx, chat.id, ApprovalKind.PLAN)
    )
    await idle(ctx, chat.id)
    run = await run_of(ctx, provider, chat.id)

    assert (allowed, denied) == ("Allowed Bash.", "Denied Write.")
    assert answered == "Answered."
    assert approved == "Approved the plan; the chat continues in acceptEdits mode."
    assert [d.behavior for d in run.decisions] == ["allow", "deny"]
    assert run.decisions[1].message == "no"
    assert run.answers[0].answers == {"Which database?": "SQLite"}
    assert run.plans[0].approved is True
    assert run.plans[0].mode == "acceptEdits"
    assert [a[0] for a in await activity(boss)][:4] == [
        "approve_plan",
        "answer_question",
        "answer_permission",
        "answer_permission",
    ]


async def test_keep_planning_and_a_strict_pixie_approves_into_default(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="answer")
    chat = await started_chat(boss, plan("1. guess", plan("2. better", reply("done"))))
    first = await pending(ctx, chat.id, ApprovalKind.PLAN)
    run = await run_of(ctx, provider, chat.id)

    kept = await boss.call("keep_planning", approval_id=first, feedback="check the tests first")

    async def second_plan() -> bool:
        approval = await ctx.approvals.pending(chat.id, ApprovalKind.PLAN)
        return approval is not None and len(run.plans) == 1

    await until(second_plan)
    approved = await boss.call(
        "approve_plan", approval_id=await pending(ctx, chat.id, ApprovalKind.PLAN)
    )
    await idle(ctx, chat.id)

    assert kept == "Sent back for more planning."
    assert run.plans[0].approved is False
    assert run.plans[0].message == "Keep planning: check the tests first"
    assert approved == "Approved the plan; the chat continues in default mode."
    assert run.plans[1].mode == "default"


async def test_answers_are_refused_outside_the_chats_it_started(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="answer")
    provider.script(ask("Bash", reply("done")))
    users = await ctx.sessions.create(CreateSession(repo="web", prompt="Mine", mode="worktree"))
    theirs = await pending(ctx, users.id, ApprovalKind.PERMISSION)

    not_mine = await boss.refused("answer_permission", approval_id=theirs, allow=True)
    wrong_kind = await boss.refused("approve_plan", approval_id=theirs)
    unknown = await boss.refused("answer_permission", approval_id="nope", allow=True)
    not_bool = await boss.refused("answer_permission", approval_id=theirs, allow="yes")

    assert not_mine == "You can only do that in chats you started."
    assert wrong_kind == "That approval is a permission, not a plan."
    assert unknown == "unknown approval 'nope'"
    assert not_bool == "allow must be true or false."
    approval = await ctx.approvals.get(theirs)
    assert approval.status is ApprovalStatus.PENDING


async def test_answers_are_checked(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider, autonomy="answer")
    chat = await started_chat(boss, question(_db_question(), reply("done")))
    approval_id = await pending(ctx, chat.id, ApprovalKind.QUESTION)

    not_an_object = await boss.refused("answer_question", approval_id=approval_id, answers="x")
    bad_value = await boss.refused(
        "answer_question", approval_id=approval_id, answers={"Which database?": 3}
    )
    unknown = await boss.refused(
        "answer_question", approval_id=approval_id, answers={"Which color?": "red"}
    )
    several = await boss.call(
        "answer_question", approval_id=approval_id, answers={"Which database?": ["SQLite"]}
    )
    again = await boss.refused(
        "answer_question", approval_id=approval_id, answers={"Which database?": "SQLite"}
    )

    assert not_an_object == "answers must map each question to an answer or a list of answers."
    assert bad_value == not_an_object
    assert unknown == "unknown questions: Which color?"
    assert several == "Answered."
    assert again == f"approval {approval_id!r} is resolved"


async def test_a_pr_card_needs_a_pull_request(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider)
    chat = await user_chat(ctx, provider)

    no_pr = await boss.refused("card", kind="pr", id=chat.id)
    wrong_kind = await boss.refused("card", kind="session", id=chat.id)
    await ctx.sessions._store.update(chat.id, pr_url="https://github.com/u/web/pull/7")  # pyright: ignore[reportPrivateUsage]
    posted = await boss.call("card", kind="pr", id=chat.id)

    assert no_pr == "That chat has no pull request."
    assert wrong_kind == (
        'kind must be "pr", "choices" or "habit_suggestion"; session cards come with the chats'
        " you start."
    )
    assert posted == "Posted the pull request's card in your chat."
    assert await boss.cards() == [{"kind": "pr", "session_id": chat.id}]
    assert await activity(boss) == [
        ("card", chat.id, "Posted a card for https://github.com/u/web/pull/7")
    ]
    events = await ctx.bus.session_events(boss.chat_id)
    assert events[-1].type == types.PIXIE_CARD
