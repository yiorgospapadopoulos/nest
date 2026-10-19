import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.context import AppContext
from nestd.errors import InvalidInputError
from nestd.events import types
from nestd.pixies.errors import (
    DuplicateSlugError,
    InvalidSlugError,
    PixieNotFoundError,
    StaleFileError,
)
from nestd.pixies.models import CreatePixie, UpdatePixie, WriteFile
from nestd.sessions.errors import SessionNotFoundError
from nestd.sessions.models import UpdateSession
from tests.api_support import build_context
from tests.async_support import until
from tests.fake_engine import FakeInfoFactory, server_info
from tests.fake_provider import FakeProvider, hang, reply
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider()


@pytest.fixture
def engine() -> FakeInfoFactory:
    return FakeInfoFactory()


@pytest.fixture
async def ctx(
    tmp_path: Path,
    clock: FakeClock,
    secrets: FakeSecretStore,
    provider: FakeProvider,
    engine: FakeInfoFactory,
) -> AsyncIterator[AppContext]:
    context = await build_context(
        tmp_path, clock, secrets, provider=provider, engine_factory=engine
    )
    yield context
    await context.sessions.shutdown()
    await context.db.close()


async def test_create_gives_unique_slugs_and_a_folder(ctx: AppContext) -> None:
    first = await ctx.pixies.create(CreatePixie(name="Tester", soul="You test."))
    second = await ctx.pixies.create(CreatePixie(name="Tester"))

    assert (first.slug, second.slug) == ("tester", "tester-2")
    assert (await ctx.pixies.read_file(first.id, "soul")).text == "You test.\n"
    assert "You are a helpful pixie" in (await ctx.pixies.read_file(second.id, "soul")).text
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

    await ctx.pixies.update(
        pixie.id, UpdatePixie(model="sonnet", effort="low", permission_mode="acceptEdits")
    )
    session = await ctx.sessions.get(chat.id)

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
    assert (await ctx.pixies.read_file(pixie.id, "soul")).text == "Keep me.\n"


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
    soul = await ctx.pixies.read_file(pixie.id, "soul")

    await ctx.pixies.write_file(pixie.id, "soul", WriteFile(text="v2", hash=soul.hash))
    with pytest.raises(StaleFileError):
        await ctx.pixies.write_file(pixie.id, "soul", WriteFile(text="v3", hash=soul.hash))
    await ctx.pixies.write_file(pixie.id, "notes/a", WriteFile(text="note", hash=None))

    assert await ctx.pixies.notes(pixie.id) == ["a"]
    assert [h.file for h in await ctx.pixies.search(pixie.id, "note")] == ["notes/a.md"]


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


async def test_settings_that_shape_the_run_open_a_fresh_one_next_turn(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"), reply("again"), reply("third"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester", project_access="edit"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))
    assert provider.runs[0].spec.write_root is None

    await ctx.pixies.update(pixie.id, UpdatePixie(project_access="none"))
    await ctx.pixies.send(pixie.id, "more", [])
    await until(lambda: len(provider.runs) == 2 and not ctx.sessions.busy(chat.id))
    soul = await ctx.pixies.read_file(pixie.id, "soul")
    await ctx.pixies.write_file(pixie.id, "soul", WriteFile(text="Be terse.", hash=soul.hash))
    await ctx.pixies.send(pixie.id, "last", [])
    await until(lambda: len(provider.runs) == 3)

    assert provider.runs[0].closed is True
    assert provider.runs[1].spec.write_root == ctx.paths.pixies_dir / pixie.id / "workdir"
    assert "Be terse." in (provider.runs[2].spec.system_prompt_append or "")


async def test_cosmetic_changes_keep_the_run(ctx: AppContext, provider: FakeProvider) -> None:
    provider.script(reply("hi"), reply("again"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    await ctx.pixies.update(pixie.id, UpdatePixie(mascot="brook", hidden=True))
    await ctx.pixies.write_file(pixie.id, "notes/a", WriteFile(text="x", hash=None))
    await ctx.pixies.send(pixie.id, "more", [])
    await until(lambda: len(provider.runs[0].inputs) == 2)

    assert len(provider.runs) == 1


async def test_a_rename_renames_the_open_chat(ctx: AppContext, provider: FakeProvider) -> None:
    provider.script(reply("hi"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    await ctx.pixies.update(pixie.id, UpdatePixie(name="Reviewer"))

    assert (await ctx.sessions.get(chat.id)).title == "Reviewer"


async def test_attachments_of_the_first_message_reach_the_agent(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    image = await ctx.attachments.save("shot.png", b"\x89PNG", "image/png")

    chat = await ctx.pixies.send(pixie.id, "look", [image.id])
    await until(lambda: bool(provider.runs and provider.runs[0].inputs))

    assert len(provider.runs[0].inputs[0].images) == 1
    assert [a.id for a in await ctx.attachments.for_session([image.id], chat.id)] == [image.id]


@pytest.mark.parametrize("pixie_id", ["..", "", "0" * 32])
async def test_files_of_an_unknown_pixie_are_not_found(ctx: AppContext, pixie_id: str) -> None:
    with pytest.raises(PixieNotFoundError):
        await ctx.pixies.read_file(pixie_id, "soul")
    with pytest.raises(PixieNotFoundError):
        await ctx.pixies.write_file(pixie_id, "soul", WriteFile(text="x", hash=None))
    with pytest.raises(PixieNotFoundError):
        await ctx.pixies.notes(pixie_id)
    with pytest.raises(PixieNotFoundError):
        await ctx.pixies.search(pixie_id, "x")


async def test_reorder_announces_only_the_pixies_that_moved(ctx: AppContext) -> None:
    a, b, c = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B", "C")]
    before = await ctx.db.fetch_one("SELECT MAX(id) AS id FROM events")
    assert before is not None

    ordered = await ctx.pixies.reorder([c.id, b.id, a.id])
    rows = await ctx.db.fetch_all(
        "SELECT type, payload FROM events WHERE id > ? ORDER BY id", (before["id"],)
    )

    assert [(p.id, p.position) for p in ordered] == [(c.id, 0), (b.id, 1), (a.id, 2)]
    assert [row["type"] for row in rows] == [types.PIXIE_UPDATED, types.PIXIE_UPDATED]
    announced = [json.loads(row["payload"])["pixie"] for row in rows]
    assert [(p["id"], p["position"]) for p in announced] == [(c.id, 0), (a.id, 2)]


async def know_models(ctx: AppContext, engine: FakeInfoFactory) -> None:
    """Default and Haiku do not run in Auto; Opus does."""
    engine.info = server_info("default", "opus", "haiku", auto=("opus",))
    assert await ctx.engine.refresh()


async def test_null_model_and_effort_go_back_to_the_default(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"), reply("again"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester", model="opus", effort="high"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    kept = await ctx.pixies.update(pixie.id, UpdatePixie.model_validate({"mascot": "brook"}))
    await ctx.pixies.update(pixie.id, UpdatePixie(model="opus"))  # no change for the chat
    cleared = await ctx.pixies.update(
        pixie.id, UpdatePixie.model_validate({"model": None, "effort": None})
    )
    session = await ctx.sessions.get(chat.id)
    await ctx.pixies.send(pixie.id, "more", [])
    await until(lambda: len(provider.runs) == 2)

    assert (kept.model, kept.effort) == ("opus", "high")
    assert (cleared.model, cleared.effort) == (None, None)
    assert (session.model, session.effort) == (None, None)
    assert (provider.runs[1].spec.model, provider.runs[1].spec.effort) == (None, None)


async def test_a_cleared_model_reaches_the_chat_as_the_default_model(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"))
    ctx.settings.agents = ctx.settings.agents.model_copy(update={"model": "sonnet"})
    pixie = await ctx.pixies.create(CreatePixie(name="Tester", model="opus"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    await ctx.pixies.update(pixie.id, UpdatePixie.model_validate({"model": None}))

    assert (await ctx.sessions.get(chat.id)).model == "sonnet"


async def test_a_model_without_auto_moves_an_auto_pixie_to_ask(
    ctx: AppContext, provider: FakeProvider, engine: FakeInfoFactory
) -> None:
    await know_models(ctx, engine)
    provider.script(reply("hi"))
    pixie = await ctx.pixies.create(
        CreatePixie(name="Tester", model="opus", permission_mode="auto")
    )
    other = await ctx.pixies.create(CreatePixie(name="Other", model="opus", permission_mode="auto"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    moved = await ctx.pixies.update(pixie.id, UpdatePixie(model="haiku"))
    cleared = await ctx.pixies.update(other.id, UpdatePixie.model_validate({"model": None}))
    session = await ctx.sessions.get(chat.id)

    assert (moved.model, moved.permission_mode) == ("haiku", "default")
    assert (session.model, session.permission_mode) == ("haiku", "default")
    assert (cleared.model, cleared.permission_mode) == (None, "default")


async def test_auto_is_refused_for_a_model_without_it(
    ctx: AppContext, engine: FakeInfoFactory
) -> None:
    await know_models(ctx, engine)
    pixie = await ctx.pixies.create(CreatePixie(name="Tester", model="haiku"))

    with pytest.raises(InvalidInputError, match="Haiku does not support Auto mode"):
        await ctx.pixies.update(pixie.id, UpdatePixie(permission_mode="auto"))
    with pytest.raises(InvalidInputError, match="Default does not support Auto mode"):
        await ctx.pixies.update(
            pixie.id, UpdatePixie.model_validate({"model": None, "permission_mode": "auto"})
        )
    with pytest.raises(InvalidInputError, match="Haiku does not support Auto mode"):
        await ctx.pixies.create(CreatePixie(name="Other", model="haiku", permission_mode="auto"))
    allowed = await ctx.pixies.update(pixie.id, UpdatePixie(model="opus", permission_mode="auto"))

    assert (allowed.model, allowed.permission_mode) == ("opus", "auto")
    assert [p.name for p in await ctx.pixies.list_pixies()] == ["Tester"]


async def test_a_chat_does_not_start_in_a_mode_its_model_lacks(
    ctx: AppContext, engine: FakeInfoFactory
) -> None:
    await know_models(ctx, engine)
    pixie = await ctx.pixies.create(
        CreatePixie(name="Tester", model="opus", permission_mode="auto")
    )
    # The model list changed since the pixie was saved.
    engine.info = server_info("default", "opus", "haiku")
    assert await ctx.engine.refresh()

    with pytest.raises(InvalidInputError, match="Opus does not support Auto mode"):
        await ctx.pixies.send(pixie.id, "hello", [])

    assert (await ctx.pixies.get(pixie.id)).chat_session_id is None
    assert await ctx.db.fetch_all("SELECT id FROM sessions") == []


async def test_a_new_autonomy_opens_a_fresh_run_that_names_it(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"), reply("again"))
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    chat = await ctx.pixies.send(pixie.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    await ctx.pixies.update(pixie.id, UpdatePixie(autonomy="start"))
    await ctx.pixies.send(pixie.id, "more", [])
    await until(lambda: len(provider.runs) == 2)

    assert "your autonomy (Observe)" in (provider.runs[0].spec.system_prompt_append or "")
    assert "your autonomy (Start)" in (provider.runs[1].spec.system_prompt_append or "")
