import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.context import AppContext
from nestd.events import types
from nestd.pixies.errors import PixieNotFoundError
from nestd.pixies.models import CreatePixie, CreateTeam, UpdatePixie, WriteFile
from tests.api_support import build_context
from tests.async_support import until
from tests.fake_provider import FakeProvider, reply
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


async def test_a_copy_has_the_settings_and_files_but_not_the_chat(
    ctx: AppContext, provider: FakeProvider
) -> None:
    provider.script(reply("hi"))
    team = await ctx.teams.create(CreateTeam(name="QA"))
    original = await ctx.pixies.create(
        CreatePixie(
            name="Tester",
            soul="You test.",
            mascot="brook",
            model="opus",
            effort="high",
            project_access="read",
            skills=["review"],
            can_call=["someone"],
        )
    )
    original = await ctx.pixies.update(original.id, UpdatePixie(team_id=team.id))
    memory = await ctx.pixies.read_file(original.id, "memory")
    await ctx.pixies.write_file(original.id, "memory", WriteFile(text="- a fact", hash=memory.hash))
    await ctx.pixies.write_file(original.id, "notes/topic", WriteFile(text="a note", hash=None))
    folder = ctx.paths.pixies_dir / original.id
    (folder / "archive" / "2026-09.md").write_text("- old fact\n", encoding="utf-8")
    (folder / "workdir" / "scratch.txt").write_text("scratch", encoding="utf-8")
    chat = await ctx.pixies.send(original.id, "hello", [])
    await until(lambda: not ctx.sessions.busy(chat.id))

    copy = await ctx.pixies.duplicate(original.id)
    copy_folder = ctx.paths.pixies_dir / copy.id

    assert (copy.name, copy.slug) == ("Tester 2", "tester-2")
    assert copy.id != original.id
    assert copy.chat_session_id is None
    assert copy.team_id == team.id
    assert (await ctx.teams.get(team.id)).leader_id == original.id
    settings = {"mascot", "model", "effort", "project_access", "skills", "can_call"}
    assert copy.model_dump(include=settings) == original.model_dump(include=settings)
    assert (await ctx.pixies.read_file(copy.id, "soul")).text == "You test.\n"
    assert (await ctx.pixies.read_file(copy.id, "memory")).text == "- a fact\n"
    assert (await ctx.pixies.read_file(copy.id, "notes/topic")).text == "a note\n"
    assert (copy_folder / "archive" / "2026-09.md").read_text(encoding="utf-8") == "- old fact\n"
    assert (copy_folder / "workdir").is_dir()
    assert list((copy_folder / "workdir").iterdir()) == []


async def test_the_copy_goes_right_after_the_original(ctx: AppContext) -> None:
    a, b, c = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B", "C")]
    row = await ctx.db.fetch_one("SELECT MAX(id) AS id FROM events")
    assert row is not None

    copy = await ctx.pixies.duplicate(a.id)
    rows = await ctx.db.fetch_all(
        "SELECT type, payload FROM events WHERE id > ? ORDER BY id", (row["id"],)
    )

    assert [p.id for p in await ctx.pixies.list_pixies()] == [a.id, copy.id, b.id, c.id]
    assert [(p.position) for p in await ctx.pixies.list_pixies()] == [0, 1, 2, 3]
    assert [r["type"] for r in rows] == [types.PIXIE_UPDATED] * 3
    announced = [json.loads(r["payload"])["pixie"] for r in rows]
    assert [(p["id"], p["position"]) for p in announced] == [(b.id, 2), (c.id, 3), (copy.id, 1)]


async def test_names_and_slugs_take_the_next_free_number(ctx: AppContext) -> None:
    original = await ctx.pixies.create(CreatePixie(name="Tester"))
    await ctx.teams.create(CreateTeam(name="Team", handle="tester-3"))
    long = await ctx.pixies.create(CreatePixie(name="x" * 40, slug="long"))

    first = await ctx.pixies.duplicate(original.id)
    second = await ctx.pixies.duplicate(original.id)
    long_copy = await ctx.pixies.duplicate(long.id)

    assert (first.name, first.slug) == ("Tester 2", "tester-2")
    # tester-3 is a team's handle.
    assert (second.name, second.slug) == ("Tester 3", "tester-4")
    assert long_copy.name == "x" * 38 + " 2"
    assert long_copy.slug == "long-2"


async def test_a_pixie_with_no_team_copies_to_no_team(ctx: AppContext) -> None:
    original = await ctx.pixies.create(CreatePixie(name="Tester"))

    copy = await ctx.pixies.duplicate(original.id)

    assert copy.team_id is None


async def test_unknown_pixie(ctx: AppContext) -> None:
    with pytest.raises(PixieNotFoundError):
        await ctx.pixies.duplicate("0" * 32)


async def test_a_copy_whose_files_fail_is_removed(
    ctx: AppContext, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = await ctx.pixies.create(CreatePixie(name="Tester"))

    def refuse(source_id: str, target_id: str) -> None:
        (ctx.paths.pixies_dir / target_id).mkdir()
        raise OSError("disk full")

    monkeypatch.setattr(ctx.pixies._files, "copy", refuse)  # type: ignore[attr-defined]

    with pytest.raises(OSError, match="disk full"):
        await ctx.pixies.duplicate(original.id)
    assert [p.id for p in await ctx.pixies.list_pixies()] == [original.id]
    assert [p.name for p in ctx.paths.pixies_dir.iterdir()] == [original.id]
