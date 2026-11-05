"""Autopilot: a chat works on without the user, and stops when it should."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from nestd.autopilot.answers import (
    DETAIL_CHARS,
    FIRST_OPTION_REASON,
    GUARDED_REASON,
    NO_OPTIONS_REASON,
)
from nestd.autopilot.models import AutopilotDecision, AutopilotReport, SetAutopilot
from nestd.autopilot.runner import (
    FIRST_RETRY,
    KEEP_GOING_TEXT,
    MAX_ERRORS,
    MAX_IDLE_TURNS,
    RESUME_TEXT,
)
from nestd.events import types
from nestd.providers.base import (
    PermissionDecision,
    PermissionRequest,
    Question,
    QuestionOption,
    QuestionRequest,
    ToolUseBlock,
)
from nestd.sessions.errors import NoTurnInProgressError
from nestd.sessions.models import Session, SessionState, UpdateSession
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import (
    FakeRun,
    Turn,
    ask,
    engine_error,
    messages,
    plan,
    question,
    reply,
    until_interrupted,
)
from tests.fakes import FakeClock
from tests.session_support import Env

ON = SetAutopilot(on=True)


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def idle_chat(env: Env, **fields: object) -> Session:
    env.provider.script(reply("hello"))
    created = await env.create(prompt="first", mode="in_place", **fields)
    return await env.reach(created.id, SessionState.IDLE)


def worked(then: Turn) -> Turn:
    """The agent called a tool, then `then` ends the turn."""
    call = ToolUseBlock(id="t1", name="Bash", input={"command": "ls"})
    return messages(([call], None), then=then)


def done(summary: str) -> Turn:
    """The agent says it is done, with the tool its run was given."""

    async def turn(run: FakeRun) -> None:
        tool = next(t for t in run.spec.nest_tools if t.name == "autopilot_finished")
        await tool.handler({"summary": summary})
        await reply("done")(run)

    return turn


def wait_then_reply(go_on: asyncio.Event, text: str) -> Turn:
    """The agent works until `go_on`, then writes `text`."""

    async def turn(run: FakeRun) -> None:
        await go_on.wait()
        await reply(text)(run)

    return turn


async def tick_until_turn(env: Env, session_id: str, count: int) -> None:
    """Tick until `count` Autopilot messages are in the chat and their turns ended."""

    async def there() -> bool:
        await env.manager.autopilot.tick()
        return len(await autopilot_messages(env, session_id)) >= count

    await until(there)


async def autopilot_messages(env: Env, session_id: str) -> list[object]:
    return [
        event.payload["text"]
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_USER_MESSAGE and event.payload.get("origin") == "autopilot"
    ]


async def reports(env: Env, session_id: str) -> list[AutopilotReport]:
    return [
        AutopilotReport.model_validate(event.payload["report"])
        for event in await env.bus.session_events(session_id)
        if event.type == types.SESSION_AUTOPILOT_REPORT
    ]


async def last_report(env: Env, session_id: str) -> AutopilotReport:
    return (await reports(env, session_id))[-1]


def last_of(kinds: list[str], kind: str) -> int:
    return len(kinds) - 1 - kinds[::-1].index(kind)


async def test_it_keeps_going_until_the_agent_says_it_is_done(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(worked(reply("more to do")), done("Fixed the bug"))

    await tick_until_turn(env, session.id, 2)
    await env.reach(session.id, SessionState.IDLE)
    await env.manager.autopilot.tick()

    ended = await env.manager.get(session.id)
    assert ended.autopilot is None
    report = await last_report(env, session.id)
    assert report.ended == "done"
    assert report.summary == "Fixed the bug"
    assert await autopilot_messages(env, session.id) == [KEEP_GOING_TEXT, KEEP_GOING_TEXT]
    # Done: nothing more goes to the agent.
    await env.manager.autopilot.tick()
    assert len(await autopilot_messages(env, session.id)) == 2


async def test_the_run_opens_in_bypass_with_commits_and_pushes_blocked(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(done("ok"))

    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.IDLE)

    spec = env.provider.runs[-1].spec
    assert spec.permission_mode == "bypassPermissions"
    assert spec.guard_git
    assert spec.guard_commits
    assert spec.resume_id == "sdk-1"
    assert spec.system_prompt_append is not None
    assert "Autopilot is on" in spec.system_prompt_append


async def test_turning_it_off_gives_the_chat_its_mode_and_git_back(env: Env) -> None:
    session = await idle_chat(env)
    before = session.permission_mode
    await env.manager.set_autopilot(session.id, ON)
    await env.manager.set_autopilot(session.id, SetAutopilot(on=False))

    ended = await env.manager.get(session.id)
    assert ended.permission_mode == before
    assert (await last_report(env, session.id)).ended == "off"
    env.provider.script(reply("back"))
    await env.manager.send(session.id, "hi", [])
    await env.reach(session.id, SessionState.IDLE)
    assert not env.provider.runs[-1].spec.guard_git


async def test_each_run_in_a_chat_leaves_its_own_report(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    await env.manager.set_autopilot(session.id, SetAutopilot(on=False))
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(done("Fixed it"))
    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.IDLE)
    await env.manager.autopilot.tick()

    assert [(r.ended, r.summary) for r in await reports(env, session.id)] == [
        ("off", None),
        ("done", "Fixed it"),
    ]


async def test_a_run_turned_off_mid_turn_reports_after_the_agents_last_message(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(wait_then_reply(go_on := asyncio.Event(), "last words"))
    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.RUNNING)

    await env.manager.set_autopilot(session.id, SetAutopilot(on=False))
    assert await reports(env, session.id) == []

    go_on.set()
    await env.reach(session.id, SessionState.IDLE)
    kinds = [event.type for event in await env.bus.session_events(session.id)]
    assert kinds.count(types.SESSION_AUTOPILOT_REPORT) == 1
    assert last_of(kinds, types.SESSION_AUTOPILOT_REPORT) > last_of(kinds, types.SESSION_MESSAGE)


async def test_a_run_stopped_mid_turn_reports_once_the_turn_ended(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(until_interrupted())
    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.RUNNING)

    await env.manager.interrupt(session.id)
    await env.reach(session.id, SessionState.INTERRUPTED)

    kinds = [event.type for event in await env.bus.session_events(session.id)]
    assert last_of(kinds, types.SESSION_AUTOPILOT_REPORT) > last_of(kinds, types.SESSION_RESULT)


async def test_a_report_waiting_for_its_turn_survives_a_closed_chat(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(until_interrupted())
    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.RUNNING)

    await env.manager.set_autopilot(session.id, SetAutopilot(on=False))
    await env.manager.close(session.id, remove_worktree=False)
    await env.manager.autopilot.tick()

    assert (await last_report(env, session.id)).ended == "off"


async def test_the_mode_cannot_change_while_it_is_on(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    with pytest.raises(Exception, match="Bypass"):
        await env.manager.update(session.id, UpdateSession(permission_mode="default"))


async def test_stop_ends_it_and_nothing_goes_on(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(until_interrupted())
    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.RUNNING)

    await env.manager.interrupt(session.id)
    await env.reach(session.id, SessionState.INTERRUPTED)
    await env.manager.autopilot.tick()

    ended = await env.manager.get(session.id)
    assert ended.autopilot is None
    assert (await last_report(env, session.id)).ended == "stopped"
    assert len(await autopilot_messages(env, session.id)) == 1


async def test_time_ending_stops_the_turn_and_ends_the_run(env: Env, clock: FakeClock) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, SetAutopilot(on=True, stop_after_minutes=30))
    env.provider.script(until_interrupted())
    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.RUNNING)

    clock.advance(timedelta(minutes=31))
    await env.manager.autopilot.tick()
    await env.reach(session.id, SessionState.INTERRUPTED)

    assert (await last_report(env, session.id)).ended == "time"


async def test_the_budget_can_change_during_a_run(env: Env, clock: FakeClock) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, SetAutopilot(on=True, stop_after_minutes=30))
    env.provider.script(until_interrupted())
    await tick_until_turn(env, session.id, 1)

    # Back to Done only: the old time no longer stops it.
    await env.manager.set_autopilot(session.id, ON)
    clock.advance(timedelta(minutes=31))
    await env.manager.autopilot.tick()

    assert (await env.manager.get(session.id)).autopilot is not None


async def test_the_weekly_cap_ends_the_run(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, SetAutopilot(on=True, weekly_cap=80))

    async def used(_session: Session) -> float:
        return 80.0

    env.manager.autopilot._weekly_used = used  # pyright: ignore[reportPrivateUsage]
    await env.manager.autopilot.tick()

    assert (await last_report(env, session.id)).ended == "weekly_cap"


async def test_an_agent_that_does_nothing_stops_the_run(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(*[reply("nothing") for _ in range(MAX_IDLE_TURNS)])

    for count in range(1, MAX_IDLE_TURNS + 1):
        await tick_until_turn(env, session.id, count)
        await env.reach(session.id, SessionState.IDLE)
    await env.manager.autopilot.tick()

    assert (await last_report(env, session.id)).ended == "stuck"


async def test_a_failed_turn_is_tried_again_later_then_it_gives_up(
    env: Env, clock: FakeClock
) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(*[engine_error("overloaded") for _ in range(MAX_ERRORS + 1)])

    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.FAILED)
    await env.manager.autopilot.tick()
    running = await env.manager.get(session.id)
    assert running.autopilot is not None
    assert running.autopilot.errors == 1
    assert running.autopilot.retry_at == clock.now() + FIRST_RETRY
    # Not before its time.
    await env.manager.autopilot.tick()
    assert len(await autopilot_messages(env, session.id)) == 1

    for count in range(2, MAX_ERRORS + 2):
        clock.advance(timedelta(hours=1))
        await tick_until_turn(env, session.id, count)
        await env.reach(session.id, SessionState.FAILED)
        await env.manager.autopilot.tick()

    assert (await last_report(env, session.id)).ended == "errors"


async def test_it_goes_on_after_a_restart(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    await env.store.update(session.id, state=SessionState.RUNNING)

    await env.manager.recover()
    env.provider.script(done("ok"))
    await tick_until_turn(env, session.id, 1)

    assert await autopilot_messages(env, session.id) == [RESUME_TEXT]


async def test_prompts_are_answered_and_reported(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    asked = QuestionRequest(
        questions=(
            Question(
                "Which one?",
                None,
                (QuestionOption("A"), QuestionOption("B", recommended=True)),
                multi_select=False,
            ),
        )
    )
    env.provider.script(question(asked, plan("# The plan", ask("Bash", done("ok")))))

    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.IDLE)
    await env.manager.autopilot.tick()

    run = env.provider.runs[-1]
    assert run.answers[0].answers == {"Which one?": "B"}
    assert run.plans[0].approved
    assert run.plans[0].mode is None
    assert run.decisions[0].behavior == "allow"
    ended = await env.manager.get(session.id)
    assert ended.permission_mode == session.permission_mode
    report = await last_report(env, session.id)
    assert [d.kind for d in report.decisions] == ["question", "plan", "allowed"]


async def test_a_prompt_that_already_waits_is_answered_when_it_goes_on(env: Env) -> None:
    env.provider.script(ask("Bash", reply("after")))
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.WAITING)

    await env.manager.set_autopilot(created.id, ON)
    await env.reach(created.id, SessionState.IDLE)

    assert env.provider.runs[-1].decisions[0].behavior == "allow"


async def test_a_new_chat_can_start_on_it_and_is_guarded_from_its_first_turn(env: Env) -> None:
    env.provider.script(done("ok"))
    created = await env.create(prompt="first", mode="in_place", autopilot=ON)
    await env.reach(created.id, SessionState.IDLE)

    spec = env.provider.runs[-1].spec
    assert spec.guard_commits
    assert spec.permission_mode == "bypassPermissions"
    await env.manager.autopilot.tick()
    assert (await last_report(env, created.id)).ended == "done"


async def test_stopping_without_a_turn_still_ends_the_run(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    with pytest.raises(NoTurnInProgressError):
        await env.manager.interrupt(session.id)
    assert (await env.manager.get(session.id)).autopilot is None


def asked(*questions: Question) -> QuestionRequest:
    return QuestionRequest(questions=questions)


def which_one(*options: QuestionOption) -> Question:
    return Question("Which one?", None, options, multi_select=False)


async def run_prompts(env: Env, turn: Turn) -> list[AutopilotDecision]:
    """Decisions of a run that gets `turn`, then ends."""
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    env.provider.script(turn)
    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.IDLE)
    await env.manager.autopilot.tick()
    return (await last_report(env, session.id)).decisions


async def test_a_decision_keeps_what_was_offered_and_why(env: Env) -> None:
    recommended = which_one(
        QuestionOption("A", "Small"), QuestionOption("B", "Fast", recommended=True)
    )
    no_description = which_one(QuestionOption("A", recommended=True))
    no_recommendation = which_one(QuestionOption("A"), QuestionOption("B"))
    no_options = which_one()
    long_plan = "# The plan\n" + "x" * (DETAIL_CHARS + 100)

    made = await run_prompts(
        env,
        question(
            asked(recommended, no_description, no_recommendation, no_options),
            plan(long_plan, done("ok")),
        ),
    )

    assert [(o.label, o.description, o.picked) for o in made[0].options] == [
        ("A", "Small", False),
        ("B", "Fast", True),
    ]
    assert made[0].answer == "B"
    assert made[0].reason == "The agent recommended it: Fast"
    assert made[1].reason == "The agent recommended it."
    assert made[2].answer == "A"
    assert made[2].options[0].picked
    assert made[2].reason == FIRST_OPTION_REASON
    assert made[3].options == []
    assert made[3].reason == NO_OPTIONS_REASON
    assert made[4].title == "The plan"
    assert made[4].detail is not None
    assert made[4].detail.startswith("# The plan")
    assert len(made[4].detail) < DETAIL_CHARS + 10


async def test_a_prompt_that_already_waited_keeps_the_same_details(env: Env) -> None:
    waiting = which_one(QuestionOption("A"), QuestionOption("B", "Fast", recommended=True))
    env.provider.script(question(asked(waiting), reply("after")))
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.WAITING)

    await env.manager.set_autopilot(created.id, ON)
    await env.reach(created.id, SessionState.IDLE)

    run = (await env.manager.get(created.id)).autopilot
    assert run is not None
    assert [(o.label, o.description, o.picked) for o in run.decisions[0].options] == [
        ("A", None, False),
        ("B", "Fast", True),
    ]
    assert run.decisions[0].reason == "The agent recommended it: Fast"


async def test_a_denied_call_says_why_and_an_allowed_one_gives_the_engines_reason(
    env: Env,
) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    runner = env.manager.autopilot

    allowed = PermissionRequest("Edit", {}, reason="It is outside the project")
    denied = PermissionRequest("Bash", {"command": "git push"})
    assert await runner.permission(session.id, allowed) == PermissionDecision("allow")
    assert await runner.permission(session.id, denied) == PermissionDecision("deny", GUARDED_REASON)

    run = (await env.manager.get(session.id)).autopilot
    assert run is not None
    assert run.decisions[0].answer == "Allowed"
    assert run.decisions[0].reason == "It is outside the project"
    assert run.decisions[1].kind == "denied"
    assert run.decisions[1].reason == GUARDED_REASON


async def test_a_decision_lands_in_the_transcript_where_it_happened(env: Env) -> None:
    session = await idle_chat(env)
    await env.manager.set_autopilot(session.id, ON)
    call = ToolUseBlock(id="t2", name="AskUserQuestion", input={})
    prompt = question(asked(which_one(QuestionOption("A"))), done("ok"))
    env.provider.script(messages(([call], None), then=prompt))

    await tick_until_turn(env, session.id, 1)
    await env.reach(session.id, SessionState.IDLE)

    events = await env.bus.session_events(session.id)
    kinds = [event.type for event in events]
    at = kinds.index(types.SESSION_AUTOPILOT_DECISION)
    assert kinds.count(types.SESSION_AUTOPILOT_DECISION) == 1
    decision = AutopilotDecision.model_validate(events[at].payload["decision"])
    assert decision.title == "Which one?"
    assert types.SESSION_MESSAGE in kinds[:at]
    assert types.SESSION_RESULT in kinds[at:]


def test_a_decision_stored_before_the_details_still_loads() -> None:
    old = {"kind": "denied", "title": "git push", "answer": "No", "at": "2026-11-04T10:00:00Z"}

    decision = AutopilotDecision.model_validate(old)

    assert decision.options == []
    assert decision.reason is None
    assert decision.detail is None
