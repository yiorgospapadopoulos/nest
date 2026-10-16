"""Report-back: one message to the pixie when the chats it started in a turn finish (B41)."""

import asyncio
import logging

import pytest

from nestd.context import AppContext
from nestd.events import types
from nestd.pixies.models import CreatePixie
from nestd.pixies.reports import REPORT_HEAD, REPORT_TAIL, ReportBack
from nestd.sessions.models import LimitPause, NewSession, Session, SessionState
from tests.async_support import until
from tests.fake_provider import FakeProvider, FakeRun, edit, engine_error, reply
from tests.fakes import START
from tests.pixie_nest_support import ctx, idle, make_boss, provider

__all__ = ["ctx", "provider"]


async def reports(ctx: AppContext, chat_id: str) -> list[str]:
    return [
        str(e.payload["text"])
        for e in await ctx.bus.session_events(chat_id)
        if e.type == types.SESSION_USER_MESSAGE and e.payload.get("origin") == "report_back"
    ]


async def test_the_chats_of_one_turn_are_reported_once_the_pixie_is_idle(
    ctx: AppContext, provider: FakeProvider
) -> None:
    boss = await make_boss(ctx, provider, autonomy="start", max_running=5)
    release = asyncio.Event()
    started: list[str] = []

    async def pixie_turn(run: FakeRun) -> None:
        tools = {tool.name: tool for tool in run.spec.tools}
        for prompt in ("Write notes", "Break"):
            text = await tools["start_session"].handler({"project": "web", "prompt": prompt})
            started.append(text.split()[2])
            # One at a time, so each chat takes its own scripted turn.
            await until(lambda: len(provider.runs) == len(started) + 1)
            await until(lambda: bool(provider.runs[-1].inputs))
        await release.wait()
        await reply("Both started.")(run)

    provider.script(
        pixie_turn,
        edit({"notes.md": "hi\n"}, reply("wrote")),
        engine_error("boom\nat line 3"),
        reply("Thanks, I will look."),
    )
    await ctx.pixies.send(boss.pixie.id, "Start two chats", [])
    await until(lambda: len(started) == 2)
    notes, broken = started
    await idle(ctx, notes)
    await until(lambda: _state(ctx, broken, SessionState.FAILED))
    # The pixie's turn still runs: nothing is reported yet.
    assert await reports(ctx, boss.chat_id) == []

    release.set()
    await until(lambda: _reported(ctx, boss.chat_id))
    await idle(ctx, boss.chat_id)

    (report,) = await reports(ctx, boss.chat_id)
    assert report.splitlines() == [
        REPORT_HEAD,
        f"- Write notes (web, chat {notes}): ready for review",
        f"- Break (web, chat {broken}): failed: boom",
        REPORT_TAIL,
    ]
    assert boss.provider.runs[0].inputs[-1].text == report
    assert [s.pixie_batch for s in await ctx.sessions.list_sessions("web")] == [None, None]


async def _state(ctx: AppContext, session_id: str, state: SessionState) -> bool:
    return (await ctx.sessions.get(session_id)).state is state


async def _reported(ctx: AppContext, chat_id: str) -> bool:
    return bool(await reports(ctx, chat_id))


def batch_chat(pixie_id: str, batch: str, title: str = "Chat") -> NewSession:
    return NewSession(
        repo="web",
        title=title,
        prompt="p",
        mode="worktree",
        cwd=None,
        model=None,
        effort=None,
        permission_mode="default",
        provider="fake",
        started_by_pixie=pixie_id,
        pixie_batch=batch,
    )


class Delivered:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.error: Exception | None = None

    async def __call__(self, pixie_id: str, text: str) -> None:
        if self.error is not None:
            raise self.error
        self.sent.append((pixie_id, text))


def watcher(ctx: AppContext, delivered: Delivered, busy: set[str] | None = None) -> ReportBack:
    return ReportBack(
        store=ctx.sessions._store,  # pyright: ignore[reportPrivateUsage]
        pixies=ctx.pixies._store,  # pyright: ignore[reportPrivateUsage]
        approvals=ctx.approvals,
        deliver=delivered,
        busy=lambda session_id: session_id in (busy or set()),
    )


async def stored(ctx: AppContext, new: NewSession, state: SessionState) -> Session:
    store = ctx.sessions._store  # pyright: ignore[reportPrivateUsage]
    created = await store.create(new)
    return await store.update(
        created.id, state=state, last_error="no disk" if state == "failed" else None
    )


async def test_each_outcome_and_only_whole_batches(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    closed = await stored(ctx, batch_chat(pixie.id, "b1", "One"), SessionState.CLOSED)
    stopped = await stored(ctx, batch_chat(pixie.id, "b1", "Two"), SessionState.INTERRUPTED)
    failed = await stored(ctx, batch_chat(pixie.id, "b1", "Three"), SessionState.FAILED)
    quiet = await stored(ctx, batch_chat(pixie.id, "b1", "Four\nlines"), SessionState.IDLE)
    waiting = await stored(ctx, batch_chat(pixie.id, "b2"), SessionState.RUNNING)
    delivered = Delivered()

    await watcher(ctx, delivered).check(pixie.id)

    ((to, text),) = delivered.sent
    assert to == pixie.id
    assert text.splitlines()[1:5] == [
        f"- One (web, chat {closed.id}): closed",
        f"- Two (web, chat {stopped.id}): interrupted",
        f"- Three (web, chat {failed.id}): failed: no disk",
        f"- Four (web, chat {quiet.id}): idle",
    ]
    store = ctx.sessions._store  # pyright: ignore[reportPrivateUsage]
    assert [s.id for s in await store.batch_members(pixie.id)] == [waiting.id]


async def test_a_chat_paused_at_the_usage_limit_has_not_finished(ctx: AppContext) -> None:
    """B78: it goes on by itself after the reset, so its batch waits for it."""
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    paused = await stored(ctx, batch_chat(pixie.id, "b1"), SessionState.IDLE)
    store = ctx.sessions._store  # pyright: ignore[reportPrivateUsage]
    pause = LimitPause(window=None, resets_at=None, resume_at=START, since=START)
    await store.update(paused.id, limit_pause=pause)
    delivered = Delivered()

    await watcher(ctx, delivered).check(pixie.id)
    await store.update(paused.id, limit_pause=None)
    await watcher(ctx, delivered).check(pixie.id)

    assert [to for to, _ in delivered.sent] == [pixie.id]


async def test_a_busy_pixie_chat_waits(ctx: AppContext, provider: FakeProvider) -> None:
    boss = await make_boss(ctx, provider)
    await stored(ctx, batch_chat(boss.pixie.id, "b1"), SessionState.IDLE)
    delivered = Delivered()

    await watcher(ctx, delivered, busy={boss.chat_id}).check(boss.pixie.id)
    store = ctx.sessions._store  # pyright: ignore[reportPrivateUsage]
    await store.update(boss.chat_id, state=SessionState.RUNNING)
    await watcher(ctx, delivered).check(boss.pixie.id)

    assert delivered.sent == []


async def test_a_pixie_without_an_open_chat_still_gets_the_report(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    await stored(ctx, batch_chat(pixie.id, "b1"), SessionState.IDLE)
    delivered = Delivered()

    await watcher(ctx, delivered).check(pixie.id)

    assert [to for to, _ in delivered.sent] == [pixie.id]


async def test_a_deleted_pixies_batches_are_dropped(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    await stored(ctx, batch_chat(pixie.id, "b1"), SessionState.IDLE)
    await ctx.pixies.delete(pixie.id)
    delivered = Delivered()

    await watcher(ctx, delivered).check(pixie.id)
    await watcher(ctx, delivered).check("nobody")

    assert delivered.sent == []
    assert await ctx.sessions._store.batch_pixies() == []  # pyright: ignore[reportPrivateUsage]


async def test_start_delivers_what_finished_before_a_restart(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    await stored(ctx, batch_chat(pixie.id, "b1"), SessionState.INTERRUPTED)
    delivered = Delivered()
    reporter = watcher(ctx, delivered)

    await reporter.start()
    await until(lambda: bool(delivered.sent))
    await reporter.stop()

    assert "interrupted" in delivered.sent[0][1]


async def test_a_failed_delivery_is_kept_and_logged(
    ctx: AppContext, caplog: pytest.LogCaptureFixture
) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    chat = await stored(ctx, batch_chat(pixie.id, "b1"), SessionState.IDLE)
    delivered = Delivered()
    delivered.error = RuntimeError("chat open elsewhere")
    reporter = watcher(ctx, delivered)

    with caplog.at_level(logging.WARNING):
        await reporter.state_changed(chat)
        await until(lambda: "chat open elsewhere" in caplog.text)
    delivered.error = None
    await reporter.purged("some-chat")
    await until(lambda: bool(delivered.sent))

    assert f"reporting finished chats to pixie {pixie.id} failed" in caplog.text


async def test_unrelated_changes_check_nothing(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    plain = await stored(
        ctx,
        batch_chat(pixie.id, "b1").model_copy(
            update={"started_by_pixie": None, "pixie_batch": None}
        ),
        SessionState.IDLE,
    )
    delivered = Delivered()
    reporter = watcher(ctx, delivered)

    await reporter.state_changed(plain)
    await reporter.stop()

    assert delivered.sent == []


async def test_stop_cancels_checks_in_progress(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Boss"))
    chat = await stored(ctx, batch_chat(pixie.id, "b1"), SessionState.IDLE)
    gate = asyncio.Event()

    async def slow(pixie_id: str, text: str) -> None:
        await gate.wait()

    reporter = ReportBack(
        store=ctx.sessions._store,  # pyright: ignore[reportPrivateUsage]
        pixies=ctx.pixies._store,  # pyright: ignore[reportPrivateUsage]
        approvals=ctx.approvals,
        deliver=slow,
        busy=lambda _session_id: False,
    )
    await reporter.state_changed(chat)
    await asyncio.sleep(0.05)

    await reporter.stop()
    # Stopped: what the daemon's shutdown changes is reported at the next start.
    await reporter.state_changed(chat)

    store = ctx.sessions._store  # pyright: ignore[reportPrivateUsage]
    assert [s.id for s in await store.batch_members(pixie.id)] == [chat.id]
    assert not reporter._tasks  # pyright: ignore[reportPrivateUsage]
