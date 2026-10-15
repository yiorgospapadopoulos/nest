"""B59: rewinding the conversation to before a user message, as Claude Code's rewind."""

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.events import types
from nestd.providers.base import (
    ApprovalHandler,
    ForkPoint,
    HookOutput,
    ProviderEventSink,
    RewindResult,
    SessionSpec,
)
from nestd.sessions.errors import CannotRewindError
from nestd.sessions.models import AttachmentSummary, RewindReply, SessionState
from nestd.sessions.rewinds import NO_CONVERSATION_POINT, NO_RUN_TO_PREVIEW
from nestd.storage.db import Database
from tests.async_support import until
from tests.fake_provider import FakeRun, echoed, reply
from tests.fakes import FakeClock
from tests.session_support import Env
from tests.test_session_control import until_results


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def two_turns(env: Env) -> tuple[str, int, int]:
    """A chat of two turns, the messages checkpointed `cp-1` and `cp-2`, whose Claude Code
    transcript is cut before them at nothing and at `a-1`.
    """
    env.provider.script(echoed("cp-1", reply("one")), echoed("cp-2", reply("two")))
    env.provider.fork_points = {
        ("sdk-1", "cp-1"): ForkPoint(None),
        ("sdk-1", "cp-2"): ForkPoint("a-1"),
    }
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "second", [])
    await until_results(env, created.id, 2)
    first, second = await user_messages(env, created.id)
    return created.id, first, second


async def user_messages(env: Env, session_id: str) -> list[int]:
    events = await env.bus.session_events(session_id)
    return [e.id for e in events if e.type == types.SESSION_USER_MESSAGE and e.id is not None]


async def texts(env: Env, session_id: str) -> list[str]:
    shown: list[str] = []
    for event in await env.bus.session_events(session_id):
        if event.type == types.SESSION_USER_MESSAGE:
            shown.append(f"user: {event.payload['text']}")
        elif event.type == types.SESSION_MESSAGE:
            blocks = event.payload["blocks"]
            assert isinstance(blocks, list)
            shown.extend(f"agent: {b['text']}" for b in blocks if isinstance(b, dict))
    return shown


async def test_rewinding_the_last_message_drops_it_and_continues_from_before_it(
    env: Env,
) -> None:
    session_id, _, second = await two_turns(env)
    old_run = env.provider.runs[0]
    last = await env.bus.last_id()

    rewound = await env.manager.rewind(session_id, second, dry_run=False, restore="conversation")

    assert rewound == RewindReply(can_rewind=True, restore="conversation", text="second")
    assert await texts(env, session_id) == ["user: first", "agent: one"]
    events = await env.bus.session_events(session_id)
    assert all(e.id is not None and e.id < second for e in events[:-1])
    assert (events[-1].type, events[-1].payload) == (
        types.SESSION_REWOUND,
        {"message": second, "through": last, "text": "second", "attachments": []},
    )
    assert await env.store.checkpoint(session_id, second) is None
    # Claude Code loads the cut at once, in a new run; only that turn is dropped.
    assert old_run.closed
    assert ("rewind_files", ("cp-2", False)) not in old_run.calls
    cut = env.provider.runs[1].spec
    assert (cut.resume_id, cut.resume_at, cut.drops_turn) == ("sdk-1", "a-1", "cp-2")
    session = await env.store.get(session_id)
    assert (session.fork_from, session.fork_at, session.fork_drops) == ("sdk-1", "a-1", "cp-2")
    assert session.state is SessionState.IDLE
    assert env.hooks.rewinds == [(session_id, True, False)]

    env.provider.script(echoed("cp-3", reply("edited answer", provider_session_id="sdk-2")))
    await env.manager.send(session_id, "second, edited", [])
    await until_results(env, session_id, 2)

    assert len(env.provider.runs) == 2
    assert await texts(env, session_id) == [
        "user: first",
        "agent: one",
        "user: second, edited",
        "agent: edited answer",
    ]
    # The cut is done: the new session is the chat's, the old one stays it as earlier.
    session = await env.store.get(session_id)
    assert session.provider_session_id == "sdk-2"
    assert (session.fork_from, session.fork_at, session.fork_drops) == (None, None, None)
    earlier = await env.manager.find_by_provider_session("sdk-1")
    assert earlier is not None
    assert earlier.id == session_id


async def test_rewinding_further_back_lets_claude_code_drop_several_turns(env: Env) -> None:
    session_id, _, second = await two_turns(env)
    env.provider.script(echoed("cp-3", reply("three")))
    await env.manager.send(session_id, "third", [])
    await until_results(env, session_id, 3)

    await env.manager.rewind(session_id, second, dry_run=False, restore="conversation")

    session = await env.store.get(session_id)
    assert (session.fork_at, session.fork_drops) == ("a-1", None)
    assert await texts(env, session_id) == ["user: first", "agent: one"]


async def test_rewinding_the_first_message_starts_the_conversation_afresh(env: Env) -> None:
    session_id, first, _ = await two_turns(env)
    (run,) = env.provider.runs

    rewound = await env.manager.rewind(session_id, first, dry_run=False, restore="conversation")
    env.provider.script(reply("fresh", provider_session_id="sdk-3"))
    await env.manager.send(session_id, "first, edited", [])
    await until(lambda: len(env.provider.runs) == 2)
    await until_results(env, session_id, 1)

    assert rewound.text == "first"
    assert run.closed
    assert env.provider.runs[1].spec.resume_id is None
    assert await texts(env, session_id) == ["user: first, edited", "agent: fresh"]
    earlier = await env.manager.find_by_provider_session("sdk-1")
    assert earlier is not None
    assert earlier.id == session_id


async def test_rewinding_both_restores_files_then_the_conversation(env: Env) -> None:
    session_id, _, second = await two_turns(env)
    old_run = env.provider.runs[0]

    rewound = await env.manager.rewind(session_id, second, dry_run=False, restore="both")

    assert rewound == RewindReply(
        can_rewind=True, files_changed=["a.py"], insertions=2, restore="both", text="second"
    )
    assert ("rewind_files", ("cp-2", False)) in old_run.calls
    events = await env.bus.session_events(session_id)
    assert [e.type for e in events[-2:]] == [types.SESSION_REWOUND, types.SESSION_NOTICE]
    assert env.hooks.rewinds == [(session_id, True, True)]


async def test_files_that_cannot_be_restored_leave_the_conversation_alone(env: Env) -> None:
    session_id, _, second = await two_turns(env)
    env.provider.rewind = RewindResult(can_rewind=False, error="Failed to rewind: gone")

    with pytest.raises(CannotRewindError, match="gone"):
        await env.manager.rewind(session_id, second, dry_run=False, restore="both")

    assert await texts(env, session_id) == [
        "user: first",
        "agent: one",
        "user: second",
        "agent: two",
    ]
    assert len(env.provider.runs) == 1
    assert env.hooks.rewinds == []


@pytest.mark.parametrize(
    ("restore", "said"),
    [
        ("conversation", "Claude Code could not rewind the conversation: Resume rejected"),
        ("both", "The files were restored, but Claude Code could not rewind the conversation"),
    ],
)
async def test_a_cut_claude_code_refuses_changes_nothing_in_the_chat(
    env: Env, restore: str, said: str
) -> None:
    session_id, _, second = await two_turns(env)
    env.provider.open_error = RuntimeError("Resume rejected by --resume-drops-turn: queued message")

    with pytest.raises(CannotRewindError, match=said):
        await env.manager.rewind(session_id, second, dry_run=False, restore=restore)  # type: ignore[arg-type]

    assert await texts(env, session_id) == [
        "user: first",
        "agent: one",
        "user: second",
        "agent: two",
    ]
    session = await env.store.get(session_id)
    assert (session.fork_from, session.fork_at, session.fork_drops) == (None, None, None)
    assert session.provider_session_id == "sdk-1"
    # The chat goes on: its next message resumes the whole conversation.
    env.provider.open_error = None
    env.provider.script(reply("still here"))
    await env.manager.send(session_id, "hello", [])
    await until_results(env, session_id, 3)
    assert env.provider.runs[-1].spec.resume_at is None


async def test_a_message_missing_from_claude_codes_transcript_is_not_rewound(env: Env) -> None:
    session_id, _, second = await two_turns(env)
    env.provider.fork_points = {}

    preview = await env.manager.rewind(session_id, second, dry_run=True, restore="conversation")
    with pytest.raises(CannotRewindError, match="does not have this message"):
        await env.manager.rewind(session_id, second, dry_run=False, restore="both")

    assert preview == RewindReply(
        can_rewind=False, error=NO_CONVERSATION_POINT, restore="conversation"
    )
    assert ("rewind_files", ("cp-2", False)) not in env.provider.runs[0].calls
    assert len(await user_messages(env, session_id)) == 2


async def test_a_conversation_preview_never_starts_claude_code(env: Env) -> None:
    session_id, _, second = await two_turns(env)
    await env.manager.close_idle_run(session_id)

    conversation = await env.manager.rewind(
        session_id, second, dry_run=True, restore="conversation"
    )
    both = await env.manager.rewind(session_id, second, dry_run=True, restore="both")

    assert conversation == RewindReply(can_rewind=True, restore="conversation", text="second")
    assert both == RewindReply(can_rewind=False, error=NO_RUN_TO_PREVIEW, restore="both")
    assert len(env.provider.runs) == 1
    assert len(await user_messages(env, session_id)) == 2


async def test_a_preview_of_both_lists_the_files_and_gives_the_message(env: Env) -> None:
    session_id, _, second = await two_turns(env)

    both = await env.manager.rewind(session_id, second, dry_run=True, restore="both")
    env.provider.rewind = RewindResult(can_rewind=False, error="Failed to rewind: gone")
    refused = await env.manager.rewind(session_id, second, dry_run=True, restore="both")

    assert both == RewindReply(
        can_rewind=True, files_changed=["a.py"], insertions=2, restore="both", text="second"
    )
    assert refused == RewindReply(can_rewind=False, error="Failed to rewind: gone", restore="both")


async def test_a_chat_without_a_claude_code_session_has_no_conversation_to_rewind(
    env: Env,
) -> None:
    session_id, _, second = await two_turns(env)
    await env.store.update(session_id, provider_session_id=None)

    preview = await env.manager.rewind(session_id, second, dry_run=True, restore="conversation")

    assert preview.can_rewind is False
    assert preview.error == NO_CONVERSATION_POINT


async def test_the_rewound_message_gives_back_its_attachments(env: Env) -> None:
    env.provider.script(echoed("cp-1", reply("one")), echoed("cp-2", reply("two")))
    env.provider.fork_points = {("sdk-1", "cp-2"): ForkPoint("a-1")}
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    image = await env.attachments.save("shot.png", b"\x89PNG", "image/png")
    await env.manager.send(created.id, "look", [image.id])
    await until_results(env, created.id, 2)
    _, second = await user_messages(env, created.id)

    rewound = await env.manager.rewind(created.id, second, dry_run=False, restore="conversation")

    assert rewound.attachments == [
        AttachmentSummary(id=image.id, filename="shot.png", media_type="image/png", size=4)
    ]


async def test_a_malformed_message_gives_back_what_it_can(env: Env) -> None:
    session_id, _, _ = await two_turns(env)
    odd = await env.bus.publish(
        types.SESSION_USER_MESSAGE, {"text": 7, "attachments": [{"id": 1}]}, session_id
    )
    other = await env.bus.publish(types.SESSION_USER_MESSAGE, {"attachments": "none"}, session_id)
    assert odd.id is not None
    assert other.id is not None
    for event_id in (odd.id, other.id):
        await env.store.save_checkpoint(session_id, event_id, f"cp-{event_id}")
        env.provider.fork_points[("sdk-1", f"cp-{event_id}")] = ForkPoint("a-2")

    first = await env.manager.rewind(session_id, odd.id, dry_run=True, restore="conversation")
    second = await env.manager.rewind(session_id, other.id, dry_run=True, restore="conversation")

    assert (first.text, first.attachments) == ("", [])
    assert (second.text, second.attachments) == ("", [])


async def test_a_message_sent_during_the_rewind_waits_and_is_kept(env: Env) -> None:
    session_id, _, second = await two_turns(env)
    env.provider.open_gate = asyncio.Event()
    env.provider.script(echoed("cp-3", reply("after the rewind")))

    rewinding = asyncio.create_task(
        env.manager.rewind(session_id, second, dry_run=False, restore="conversation")
    )
    await until(lambda: env.provider.runs[0].closed)
    sent = await env.manager.send(session_id, "meanwhile", [])
    env.provider.open_gate.set()
    await rewinding
    await until_results(env, session_id, 2)

    assert sent.queued_message is not None
    assert await texts(env, session_id) == [
        "user: first",
        "agent: one",
        "user: meanwhile",
        "agent: after the rewind",
    ]


async def test_a_message_without_a_checkpoint_is_not_rewound(env: Env) -> None:
    env.provider.script(reply("one"))
    created = await env.create(prompt="first", mode="in_place")
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)

    with pytest.raises(CannotRewindError, match="no file checkpoint"):
        await env.manager.rewind(created.id, message, dry_run=False, restore="conversation")


async def test_what_the_cut_run_says_as_it_opens_stays_in_the_chat(
    env: Env, monkeypatch: pytest.MonkeyPatch
) -> None:
    session_id, _, second = await two_turns(env)
    original = env.provider.open

    async def opening(
        spec: SessionSpec, handler: ApprovalHandler, sink: ProviderEventSink
    ) -> FakeRun:
        run = await original(spec, handler, sink)
        await sink.hook(
            HookOutput(
                hook_name="SessionStart:resume",
                hook_event="SessionStart",
                outcome="success",
                output="Loaded the notes",
            )
        )
        return run

    monkeypatch.setattr(env.provider, "open", opening)

    await env.manager.rewind(session_id, second, dry_run=False, restore="conversation")

    events = await env.bus.session_events(session_id)
    assert [e.type for e in events[-2:]] == [types.SESSION_HOOK, types.SESSION_REWOUND]
    assert await texts(env, session_id) == ["user: first", "agent: one"]
