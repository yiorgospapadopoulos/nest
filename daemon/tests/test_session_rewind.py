"""IMP-02: restoring the files of a chat to before one of the user's messages."""

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from pathlib import Path

import pytest

from harness.events import types
from harness.providers.base import RewindResult
from harness.sessions.errors import CannotRewindError, SessionBusyError, SessionClosedError
from harness.sessions.models import SessionState
from harness.storage.db import Database
from tests.async_support import until
from tests.fake_provider import echoed, hang, reply
from tests.fakes import FakeClock
from tests.session_support import Env
from tests.test_session_control import until_results


@pytest.fixture
async def env(tmp_path: Path, db: Database, clock: FakeClock) -> AsyncIterator[Env]:
    environment = Env(tmp_path, db, clock)
    await environment.register()
    yield environment
    await environment.manager.shutdown()


async def user_messages(env: Env, session_id: str) -> list[int]:
    events = await env.bus.session_events(session_id)
    return [e.id for e in events if e.type == types.SESSION_USER_MESSAGE and e.id is not None]


async def notices(env: Env, session_id: str) -> list[object]:
    events = await env.bus.session_events(session_id)
    return [e.payload for e in events if e.type == types.SESSION_NOTICE]


async def test_each_message_keeps_its_checkpoint_for_a_preview(env: Env) -> None:
    env.provider.script(echoed("msg-1", reply("one")), echoed("msg-2", reply("two")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    await env.manager.send(created.id, "and more", [])
    await until_results(env, created.id, 2)
    first, second = await user_messages(env, created.id)

    preview = await env.manager.rewind(created.id, first, dry_run=True)
    await env.manager.rewind(created.id, second, dry_run=True)

    assert preview == RewindResult(can_rewind=True, files_changed=["a.py"], insertions=2)
    assert env.provider.runs[0].calls == [
        ("rewind_files", ("msg-1", True)),
        ("rewind_files", ("msg-2", True)),
    ]
    # A preview changes nothing the user sees.
    assert await notices(env, created.id) == []


async def test_only_the_first_echo_of_a_message_is_its_checkpoint(env: Env) -> None:
    env.provider.script(echoed("msg-1", echoed("msg-x", reply("one"))))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)

    assert await env.store.checkpoint(created.id, message) == "msg-1"


async def test_a_chat_being_closed_is_not_restored(env: Env) -> None:
    env.provider.script(echoed("msg-1", reply("one")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)
    env.manager._live[created.id].stopped = True  # pyright: ignore[reportPrivateUsage]

    with pytest.raises(SessionBusyError):
        await env.manager.rewind(created.id, message, dry_run=True)


@pytest.mark.parametrize(
    ("files", "text"),
    [
        (["a.py"], "Restored 1 file to before your message"),
        (["a.py", "b.py"], "Restored 2 files to before your message"),
        ([], "Restored files to before your message"),
    ],
)
async def test_restoring_files_is_noted_in_the_chat(env: Env, files: list[str], text: str) -> None:
    env.provider.script(echoed("msg-1", reply("one")))
    env.provider.rewind = RewindResult(can_rewind=True, files_changed=files)
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)

    restored = await env.manager.rewind(created.id, message, dry_run=False)

    assert restored.files_changed == files
    assert env.provider.runs[0].calls == [("rewind_files", ("msg-1", False))]
    assert await notices(env, created.id) == [{"kind": "files_restored", "text": text}]
    # Only files: the conversation goes on in the same run.
    assert env.provider.runs[0].closed is False


async def test_a_message_without_a_checkpoint_cannot_be_restored_to(env: Env) -> None:
    """Such as a message of a chat continued from Claude Code, or a slash command."""
    env.provider.script(reply("one"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)

    preview = await env.manager.rewind(created.id, message, dry_run=True)
    with pytest.raises(CannotRewindError, match="no file checkpoint"):
        await env.manager.rewind(created.id, message, dry_run=False)

    assert preview.can_rewind is False
    assert preview.error is not None
    assert "no file checkpoint" in preview.error
    assert env.provider.runs[0].calls == []


async def test_a_restore_the_engine_refuses_says_why(env: Env) -> None:
    env.provider.script(echoed("msg-1", reply("one")))
    env.provider.rewind = RewindResult(can_rewind=False, error="Failed to rewind: gone")
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)

    with pytest.raises(CannotRewindError, match="Failed to rewind: gone") as raised:
        await env.manager.rewind(created.id, message, dry_run=False)

    assert raised.value.payload() == {
        "detail": "Failed to rewind: gone",
        "code": "cannot_rewind",
    }
    assert await notices(env, created.id) == []


async def test_files_are_restored_only_while_the_chat_is_idle(env: Env) -> None:
    env.provider.script(echoed("msg-1", hang()))
    created = await env.create()
    await env.reach(created.id, SessionState.RUNNING)

    async def stored() -> bool:
        return bool(
            await env.store.checkpoint(created.id, (await user_messages(env, created.id))[0])
        )

    await until(stored)
    (message,) = await user_messages(env, created.id)

    with pytest.raises(SessionBusyError, match="idle"):
        await env.manager.rewind(created.id, message, dry_run=True)


async def test_a_closed_chat_cannot_be_restored(env: Env) -> None:
    env.provider.script(echoed("msg-1", reply("one")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)
    await env.manager.close(created.id, remove_worktree=False)

    with pytest.raises(SessionClosedError):
        await env.manager.rewind(created.id, message, dry_run=True)


async def test_an_idle_closed_run_is_resumed_to_restore(env: Env) -> None:
    env.provider.script(echoed("msg-1", reply("one")))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)
    await env.manager.shutdown()
    env.manager = env.build(timedelta(hours=1))

    restored = await env.manager.rewind(created.id, message, dry_run=False)

    assert restored.can_rewind is True
    run = env.provider.runs[1]
    assert run.spec.resume_id == "sdk-1"
    assert run.calls == [("rewind_files", ("msg-1", False))]
    # No message reaches the agent.
    assert run.inputs == []
    assert (await env.store.get(created.id)).state is SessionState.IDLE


async def test_a_message_sent_while_restoring_starts_afterwards(env: Env) -> None:
    env.provider.script(echoed("msg-1", reply("one")), reply("two"))
    created = await env.create()
    await env.reach(created.id, SessionState.IDLE)
    (message,) = await user_messages(env, created.id)
    await env.manager.shutdown()
    env.manager = env.build(timedelta(hours=1))
    env.provider.open_gate = asyncio.Event()

    restoring = asyncio.ensure_future(env.manager.rewind(created.id, message, dry_run=False))
    await until(lambda: env.manager.busy(created.id))
    sent = await env.manager.send(created.id, "carry on", [])
    env.provider.open_gate.set()
    await restoring
    await until_results(env, created.id, 2)

    assert sent.queued_message is not None
    assert env.provider.runs[1].calls == [("rewind_files", ("msg-1", False))]
    assert [i.text for i in env.provider.runs[1].inputs] == ["carry on"]
