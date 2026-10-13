import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from harness.context import AppContext
from harness.events import types
from harness.pixies.errors import (
    DuplicateSlugError,
    InvalidSlugError,
    PixieNotFoundError,
    StaleFileError,
)
from harness.pixies.models import CreatePixie, UpdatePixie, WriteFile
from harness.sessions.errors import SessionNotFoundError
from harness.sessions.models import UpdateSession
from tests.api_support import build_context
from tests.async_support import until
from tests.fake_provider import FakeProvider, hang, reply
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
async def ctx(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, provider: FakeProvider
) -> AsyncIterator[AppContext]:
    context = await build_context(tmp_path, clock, secrets, provider=provider)
    yield context
    await context.sessions.shutdown()
    await context.db.close()


async def test_create_gives_unique_slugs_and_a_folder(ctx: AppContext) -> None:
    first = await ctx.pixies.create(CreatePixie(name="Tester", soul="You test."))
    second = await ctx.pixies.create(CreatePixie(name="Tester"))

    assert (first.slug, second.slug) == ("tester", "tester-2")
    assert ctx.pixies.read_file(first.id, "soul").text == "You test.\n"
    assert "You are a helpful pixie" in ctx.pixies.read_file(second.id, "soul").text
    with pytest.raises(InvalidSlugError):
        await ctx.pixies.create(CreatePixie(name="Planner", slug="plan"))
    with pytest.raises(DuplicateSlugError):
        await ctx.pixies.create(CreatePixie(name="Other", slug="tester"))
    with pytest.raises(DuplicateSlugError):
        await ctx.pixies.update(second.id, UpdatePixie(slug="tester"))


async def test_the_first_message_starts_the_chat_and_later_ones_continue_it(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"), reply("again"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester", model="opus", effort="high"))

    first = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: bool(provider.runs and provider.runs[0].inputs))
    stored = await ctx.pixies.get(pixie.id)
    await until(lambda: not ctx.sessions.busy(first.id))
    second = await ctx.pixies.send(pixie.id, "more", [])

    assert stored.chat_session_id == first.id
    assert second.id == first.id
    assert first.model == "opus"
    assert first.effort == "high"
    assert first.cwd == ctx.paths.pixies_dir / pixie.id / "workdir"


async def test_updating_controls_reaches_the_open_chat(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    updated = await ctx.pixies.update(
        pixie.id,
        UpdatePixie(model="sonnet", effort="low", permission_mode="acceptEdits", projects=["web"]),
    )
    cleared = await ctx.pixies.update(pixie.id, UpdatePixie(all_projects=True))
    session = await ctx.sessions.get(chat.id)

    assert updated.projects == ["web"]
    assert cleared.projects is None
    assert session.model == "sonnet"
    assert session.effort == "low"
    assert session.permission_mode == "acceptEdits"


async def test_reset_archives_the_chat_and_keeps_soul_and_memory(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"), reply("new"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester", soul="Keep me."))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    reset = await ctx.pixies.reset(pixie.id)
    fresh = await ctx.pixies.send(pixie.id, "again", [])

    assert reset.chat_session_id is None
    assert (await ctx.sessions.get(chat.id)).archived_at is not None
    assert fresh.id != chat.id
    assert ctx.pixies.read_file(pixie.id, "soul").text == "Keep me.\n"


async def test_delete_mid_turn_removes_everything(ctx: AppContext, provider: FakeProvider) -> None:
    provider.script(hang())
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "work forever", [])
    await until(lambda: ctx.sessions.busy(chat.id))

    await ctx.pixies.delete(pixie.id)

    with pytest.raises(PixieNotFoundError):
        await ctx.pixies.get(pixie.id)
    with pytest.raises(SessionNotFoundError):
        await ctx.sessions.get(chat.id)
    assert not (ctx.paths.pixies_dir / pixie.id).exists()


async def test_files_conflict_on_stale_hashes(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    soul = ctx.pixies.read_file(pixie.id, "soul")

    ctx.pixies.write_file(pixie.id, "soul", WriteFile(text="v2", hash=soul.hash))
    with pytest.raises(StaleFileError):
        ctx.pixies.write_file(pixie.id, "soul", WriteFile(text="v3", hash=soul.hash))
    ctx.pixies.write_file(pixie.id, "notes/a", WriteFile(text="note", hash=None))

    assert ctx.pixies.notes(pixie.id) == ["a"]
    assert [h.file for h in ctx.pixies.search(pixie.id, "note")] == ["notes/a.md"]


async def test_events_are_published(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    await ctx.pixies.update(pixie.id, UpdatePixie(name="QA"))
    await ctx.pixies.delete(pixie.id)

    rows = await ctx.db.fetch_all("SELECT type FROM events WHERE type LIKE 'pixie.%' ORDER BY id")

    assert [row["type"] for row in rows] == [
        types.PIXIE_UPDATED,
        types.PIXIE_UPDATED,
        types.PIXIE_DELETED,
    ]


async def test_a_name_that_slugifies_to_a_reserved_slug_gets_a_free_one(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Plan"))

    assert pixie.slug == "plan-2"
    assert [p.id for p in await ctx.pixies.list_pixies()] == [pixie.id]
    with pytest.raises(InvalidSlugError):
        await ctx.pixies.update(pixie.id, UpdatePixie(slug="explore"))


async def test_a_dead_chat_is_replaced_by_a_new_one(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"), reply("new"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))
    # Foreign keys would stop a purge of the current chat; this is a row lost some other way.
    await ctx.db.execute("PRAGMA foreign_keys = OFF")
    await ctx.sessions.purge(chat.id)
    await ctx.db.execute("PRAGMA foreign_keys = ON")

    fresh = await ctx.pixies.send(pixie.id, "again", [])

    assert fresh.id != chat.id
    assert (await ctx.pixies.get(pixie.id)).chat_session_id == fresh.id


async def test_reset_without_a_chat_just_clears(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))

    assert (await ctx.pixies.reset(pixie.id)).chat_session_id is None


async def test_a_long_name_keeps_unique_slugs_within_the_limit(ctx: AppContext) -> None:
    name = "a" * 40
    first = await ctx.pixies.create(CreatePixie(name=name))
    second = await ctx.pixies.create(CreatePixie(name=name))

    assert len(first.slug) == 32
    assert len(second.slug) == 32
    assert first.slug != second.slug


async def test_an_archived_chat_is_replaced_by_a_new_one(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"), reply("new"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))
    await ctx.sessions.update(chat.id, UpdateSession(archived=True))

    fresh = await ctx.pixies.send(pixie.id, "again", [])

    assert fresh.id != chat.id


async def test_updating_a_pixie_whose_chat_is_gone_still_succeeds(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))
    await ctx.db.execute("PRAGMA foreign_keys = OFF")
    await ctx.sessions.purge(chat.id)
    await ctx.db.execute("PRAGMA foreign_keys = ON")

    updated = await ctx.pixies.update(pixie.id, UpdatePixie(model="sonnet"))

    assert updated.model == "sonnet"


async def test_a_failed_folder_leaves_no_pixie_behind(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(pixie_id: str, soul: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(ctx.pixies._files, "create", refuse)  # type: ignore[attr-defined]

    with pytest.raises(OSError, match="disk full"):
        await ctx.pixies.create(CreatePixie(name="Tester"))

    assert await ctx.pixies.list_pixies() == []


async def test_two_first_messages_make_one_chat(ctx: AppContext, provider: FakeProvider) -> None:
    provider.script(reply("one"), reply("two"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))

    first, second = await asyncio.gather(
        ctx.pixies.send(pixie.id, "a", []), ctx.pixies.send(pixie.id, "b", [])
    )

    assert first.id == second.id
    assert await ctx.pixies._store.chat_sessions(pixie.id) == [first.id]  # type: ignore[attr-defined]


async def test_deleting_while_a_first_message_is_being_sent(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.open_gate = asyncio.Event()
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))

    sending = asyncio.create_task(ctx.pixies.send(pixie.id, "hello", []))
    await asyncio.sleep(0)
    deleting = asyncio.create_task(ctx.pixies.delete(pixie.id))
    results = await asyncio.gather(sending, deleting, return_exceptions=True)
    provider.open_gate.set()

    assert [
        r for r in results if isinstance(r, Exception) and not isinstance(r, PixieNotFoundError)
    ] == []
    with pytest.raises(PixieNotFoundError):
        await ctx.pixies.get(pixie.id)
    assert await ctx.sessions.list_sessions() == []
    rows = await ctx.db.fetch_all("SELECT id FROM sessions")
    assert rows == []
    assert not (ctx.paths.pixies_dir / pixie.id).exists()


async def test_reset_waits_for_a_message_being_sent(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))

    chat, reset = await asyncio.gather(
        ctx.pixies.send(pixie.id, "hello", []), ctx.pixies.reset(pixie.id)
    )

    assert reset.chat_session_id is None
    assert (await ctx.sessions.get(chat.id)).archived_at is not None
