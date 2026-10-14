"""A pixie's habit tools and its reply and suggested-habit cards (B42)."""

import pytest
from pydantic import JsonValue

from harness.context import AppContext
from harness.events import types
from harness.pixies.habit_tools import REPORT_TOOL_NAMES
from harness.pixies.harness_tools import HARNESS_TOOL_NAMES
from harness.pixies.tools import TOOL_NAMES
from harness.providers.base import AgentTool, ToolRefusedError
from tests.fake_provider import FakeProvider, FakeRun, reply
from tests.habit_support import (
    cards,
    chat_tools,
    ctx,
    make_habit,
    make_pixie,
    provider,
    published,
    run_now,
    tools,
)

__all__ = ["ctx", "provider"]


async def call(tool: AgentTool, **args: JsonValue) -> str:
    return await tool.handler(args)


async def refused(tool: AgentTool, **args: JsonValue) -> str:
    with pytest.raises(ToolRefusedError) as refusal:
        await tool.handler(args)
    return str(refusal.value)


async def activity(ctx: AppContext, pixie_id: str) -> list[tuple[str, str | None, str]]:
    return [(a.tool, a.session_id, a.summary) for a in await ctx.pixies.activity(pixie_id)][::-1]


async def test_reply_buttons(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    chat_id, chat = await chat_tools(ctx, provider, pixie)

    posted = await call(chat["card"], kind="choices", options=[" Yes, merge it ", "Not yet"])

    assert posted == (
        "Posted the reply buttons; the one the user taps comes back as their message."
    )
    assert await cards(ctx, chat_id) == [
        {"kind": "choices", "options": ["Yes, merge it", "Not yet"]}
    ]
    assert await activity(ctx, pixie.id) == [
        ("card", None, "Offered replies: Yes, merge it / Not yet")
    ]


@pytest.mark.parametrize(
    "options",
    [None, "Yes", [], ["a", "b", "c", "d", "e"], ["Yes", " "], ["Yes", 2], ["x" * 81]],
)
async def test_reply_buttons_need_one_to_four_short_options(
    ctx: AppContext, provider: FakeProvider, options: JsonValue
) -> None:
    pixie = await make_pixie(ctx)
    chat_id, chat = await chat_tools(ctx, provider, pixie)

    refusal = await refused(chat["card"], kind="choices", options=options)

    assert refusal == "options must be 1 to 4 replies, each 1 to 80 characters."
    assert await cards(ctx, chat_id) == []


async def test_a_suggested_habit(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    chat_id, chat = await chat_tools(ctx, provider, pixie)

    posted = await call(
        chat["card"],
        kind="habit_suggestion",
        name="Morning CI",
        prompt="Check CI on main; report failures.",
        schedule={"kind": "weekdays", "time": "09:00"},
        id="ignored",
    )
    no_start = await refused(chat["card"], kind="habit_suggestion", name="N", prompt="P")
    unknown = await refused(chat["card"], kind="poll")

    assert posted == "Posted the suggested habit; nothing runs until the user starts it."
    assert await cards(ctx, chat_id) == [
        {
            "kind": "habit_suggestion",
            "habit": {
                "name": "Morning CI",
                "prompt": "Check CI on main; report failures.",
                "schedule": {"kind": "weekdays", "time": "09:00"},
                "triggers": [],
            },
        }
    ]
    assert no_start == "a habit needs a schedule or at least one trigger."
    assert unknown.startswith('kind must be "pr", "choices" or "habit_suggestion"')
    assert await activity(ctx, pixie.id) == [("card", None, 'Suggested the habit "Morning CI"')]
    # Nothing was created.
    assert await ctx.habits.list_habits(pixie.id) == []


async def test_a_habit_run_has_the_tools_but_posts_no_cards(
    ctx: AppContext, provider: FakeProvider
) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id)
    seen: dict[str, AgentTool] = {}
    refusals: list[str] = []

    async def turn(run: FakeRun) -> None:
        seen.update(tools(run))
        refusals.append(await refused(seen["card"], kind="choices", options=["Yes"]))
        await reply("ok")(run)

    provider.script(turn)
    run = await run_now(ctx, habit)

    assert tuple(seen) == TOOL_NAMES + HARNESS_TOOL_NAMES + REPORT_TOOL_NAMES
    assert refusals == ["A habit run has no chat to post cards in; use report instead."]
    assert await cards(ctx, run.session_id or "") == []


async def test_create_list_update_and_pause_habits(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    other = await make_pixie(ctx, "Other")
    theirs = await make_habit(ctx, other.id)
    _chat_id, chat = await chat_tools(ctx, provider, pixie)

    empty = await call(chat["habit_list"])
    created = await call(
        chat["habit_create"],
        name="Morning CI",
        prompt="Check CI.",
        schedule={"kind": "weekdays", "time": "09:00"},
        triggers=["ci_failed"],
        max_minutes=10,
    )
    [habit] = await ctx.habits.list_habits(pixie.id)
    changed = await call(
        chat["habit_update"], id=habit.id, name="CI watch", schedule=None, max_minutes=15
    )
    paused = await call(chat["habit_pause"], id=habit.id, paused=True)
    listed = await call(chat["habit_list"])
    resumed = await call(chat["habit_pause"], id=habit.id, paused=False)

    line = f"{habit.id} | CI watch | no schedule | triggers: ci_failed"
    assert empty == "You have no habits."
    assert created == (
        f"Created habit {habit.id}: {habit.id} | Morning CI | Weekdays at 09:00 | triggers:"
        " ci_failed | on | never run"
    )
    assert (habit.max_minutes, habit.enabled) == (10, True)
    assert changed == f"Changed: {line} | on | never run"
    assert paused == f"Paused: {line} | paused | never run"
    assert listed == f"{line} | paused | never run"
    assert resumed == f"Resumed: {line} | on | never run"
    assert (await ctx.habits.get(pixie.id, habit.id)).max_minutes == 15
    assert await activity(ctx, pixie.id) == [
        ("habit_create", None, 'Created habit "Morning CI"'),
        ("habit_update", None, 'Changed habit "CI watch"'),
        ("habit_pause", None, 'Paused habit "CI watch"'),
        ("habit_pause", None, 'Resumed habit "CI watch"'),
    ]
    # Only its own habits.
    assert await refused(chat["habit_pause"], id=theirs.id, paused=True) == (
        f"unknown habit {theirs.id!r}"
    )
    assert len(await published(ctx, types.HABIT_UPDATED)) >= 4


async def test_habit_tools_refuse_bad_input(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    habit = await make_habit(ctx, pixie.id, triggers=["stuck"])
    _chat_id, chat = await chat_tools(ctx, provider, pixie)

    no_prompt = await refused(chat["habit_create"], name="N", triggers=["stuck"])
    bad_trigger = await refused(chat["habit_create"], name="N", prompt="P", triggers=["merged"])
    no_id = await refused(chat["habit_update"], name="N")
    extra = await refused(chat["habit_update"], id=habit.id, color="red")
    nothing_left = await refused(chat["habit_update"], id=habit.id, schedule=None, triggers=[])
    not_bool = await refused(chat["habit_pause"], id=habit.id, paused="yes")

    assert no_prompt == "prompt: Field required."
    assert bad_trigger.startswith("triggers.0: Input should be 'stuck', 'failed'")
    assert no_id == "id is required."
    assert extra == "color: Extra inputs are not permitted."
    assert nothing_left == "a habit needs a schedule or at least one trigger"
    assert not_bool == "paused must be true or false."
    assert await activity(ctx, pixie.id) == []


async def test_habit_list_shows_the_last_run(ctx: AppContext, provider: FakeProvider) -> None:
    pixie = await make_pixie(ctx)
    _chat_id, chat = await chat_tools(ctx, provider, pixie)
    habit = await make_habit(ctx, pixie.id, schedule={"kind": "hourly", "minute": 5})
    provider.script(reply("ok"))
    await run_now(ctx, habit)

    listed = await call(chat["habit_list"])

    assert listed == (
        f"{habit.id} | Check | Every hour at :05 | triggers: none | on | last run quiet"
    )
