import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from nestd.context import AppContext
from nestd.events import types
from nestd.pixies.errors import (
    DuplicateSlugError,
    InvalidSlugError,
    LeaderNotMemberError,
    TeamNotFoundError,
)
from nestd.pixies.models import CreatePixie, CreateTeam, UpdatePixie, UpdateTeam
from tests.api_support import build_context
from tests.fakes import FakeClock, FakeSecretStore


@pytest.fixture
async def ctx(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> AsyncIterator[AppContext]:
    context = await build_context(tmp_path, clock, secrets)
    yield context
    await context.sessions.shutdown()
    await context.db.close()


async def events_since(ctx: AppContext, after: int) -> list[tuple[str, dict[str, object]]]:
    rows = await ctx.db.fetch_all(
        "SELECT type, payload FROM events WHERE id > ? AND type LIKE 'pixie%' ORDER BY id",
        (after,),
    )
    return [(row["type"], json.loads(row["payload"])) for row in rows]


async def last_event(ctx: AppContext) -> int:
    row = await ctx.db.fetch_one("SELECT COALESCE(MAX(id), 0) AS id FROM events")
    assert row is not None
    return int(row["id"])


async def test_create_list_rename_and_change_handle(ctx: AppContext) -> None:
    qa = await ctx.teams.create(CreateTeam(name="  QA crew "))
    docs = await ctx.teams.create(CreateTeam(name="Docs", handle="writers"))
    after = await last_event(ctx)

    renamed = await ctx.teams.update(qa.id, UpdateTeam(name="QA", handle="qa-crew"))
    moved = await ctx.teams.update(docs.id, UpdateTeam(handle="docs"))

    assert (qa.name, qa.handle, qa.leader_id, qa.position) == ("QA crew", "qa-crew", None, 0)
    assert (docs.handle, docs.position) == ("writers", 1)
    assert (renamed.name, renamed.handle) == ("QA", "qa-crew")
    assert moved.handle == "docs"
    assert [t.id for t in await ctx.teams.list_teams()] == [qa.id, docs.id]
    assert await events_since(ctx, after) == [
        (types.PIXIE_TEAM_UPDATED, {"team": renamed.model_dump(mode="json")}),
        (types.PIXIE_TEAM_UPDATED, {"team": moved.model_dump(mode="json")}),
    ]


async def test_handles_and_slugs_share_one_namespace(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="Tester"))
    team = await ctx.teams.create(CreateTeam(name="QA"))
    derived_team = await ctx.teams.create(CreateTeam(name="Tester"))
    derived_pixie = await ctx.pixies.create(CreatePixie(name="QA"))
    reserved = await ctx.teams.create(CreateTeam(name="Plan"))

    assert (derived_team.handle, derived_pixie.slug, reserved.handle) == (
        "tester-2",
        "qa-2",
        "plan-2",
    )
    with pytest.raises(DuplicateSlugError, match="@tester"):
        await ctx.teams.create(CreateTeam(name="X", handle="tester"))
    with pytest.raises(DuplicateSlugError, match="@qa"):
        await ctx.teams.create(CreateTeam(name="X", handle="qa"))
    with pytest.raises(DuplicateSlugError, match="@tester"):
        await ctx.teams.update(team.id, UpdateTeam(handle="tester"))
    with pytest.raises(DuplicateSlugError, match="@tester-2"):
        await ctx.teams.update(team.id, UpdateTeam(handle="tester-2"))
    with pytest.raises(DuplicateSlugError, match="@qa"):
        await ctx.pixies.create(CreatePixie(name="X", slug="qa"))
    with pytest.raises(DuplicateSlugError, match="@qa"):
        await ctx.pixies.update(pixie.id, UpdatePixie(slug="qa"))
    with pytest.raises(InvalidSlugError):
        await ctx.teams.create(CreateTeam(name="X", handle="explore"))
    with pytest.raises(InvalidSlugError):
        await ctx.teams.update(team.id, UpdateTeam(handle="Bad Handle"))
    # Keeping its own handle is no conflict.
    assert (await ctx.teams.update(team.id, UpdateTeam(handle="qa"))).handle == "qa"


async def test_the_first_member_leads_and_the_next_one_takes_over(ctx: AppContext) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA"))
    a, b, c = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B", "C")]
    after = await last_event(ctx)

    joined = await ctx.pixies.update(b.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(c.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(a.id, UpdatePixie(team_id=team.id))
    led_by_b = await ctx.teams.get(team.id)
    left = await ctx.pixies.update(b.id, UpdatePixie(team_id=None))
    led_by_a = await ctx.teams.get(team.id)
    events = await events_since(ctx, after)

    assert joined.team_id == team.id
    assert led_by_b.leader_id == b.id
    assert left.team_id is None
    # The next member in pixie order, not in joining order.
    assert led_by_a.leader_id == a.id
    leaders = [p["team"]["leader_id"] for t, p in events if t == types.PIXIE_TEAM_UPDATED]  # type: ignore[index]
    assert leaders == [b.id, a.id]

    await ctx.pixies.update(a.id, UpdatePixie(team_id=None))
    await ctx.pixies.update(c.id, UpdatePixie(team_id=None))
    assert (await ctx.teams.get(team.id)).leader_id is None


async def test_moving_to_another_team_hands_over_and_takes_the_lead(ctx: AppContext) -> None:
    qa = await ctx.teams.create(CreateTeam(name="QA"))
    docs = await ctx.teams.create(CreateTeam(name="Docs"))
    a, b = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B")]
    await ctx.pixies.update(a.id, UpdatePixie(team_id=qa.id))
    await ctx.pixies.update(b.id, UpdatePixie(team_id=qa.id))
    after = await last_event(ctx)

    # Unchanged team: nothing to hand over.
    await ctx.pixies.update(a.id, UpdatePixie(team_id=qa.id, name="A1"))
    unchanged = await events_since(ctx, after)
    await ctx.pixies.update(a.id, UpdatePixie(team_id=docs.id))

    assert [t for t, _ in unchanged] == [types.PIXIE_UPDATED]
    assert (await ctx.teams.get(qa.id)).leader_id == b.id
    assert (await ctx.teams.get(docs.id)).leader_id == a.id
    # Leaving out team_id keeps the team.
    assert (await ctx.pixies.update(a.id, UpdatePixie(name="A2"))).team_id == docs.id


async def test_set_leader_must_name_a_member(ctx: AppContext) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA"))
    a, b, outsider = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B", "O")]
    await ctx.pixies.update(a.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(b.id, UpdatePixie(team_id=team.id))

    changed = await ctx.teams.update(team.id, UpdateTeam(leader_id=b.id))
    with pytest.raises(LeaderNotMemberError) as refused:
        await ctx.teams.update(team.id, UpdateTeam(leader_id=outsider.id))
    with pytest.raises(LeaderNotMemberError):
        await ctx.teams.update(team.id, UpdateTeam(leader_id="no-such-pixie"))

    assert changed.leader_id == b.id
    assert refused.value.status_code == 409
    assert refused.value.payload()["code"] == "leader_not_member"
    assert (await ctx.teams.get(team.id)).leader_id == b.id


async def test_deleting_the_leader_hands_over(ctx: AppContext) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA"))
    a, b = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B")]
    await ctx.pixies.update(a.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(b.id, UpdatePixie(team_id=team.id))

    await ctx.pixies.delete(a.id)
    after_a = await ctx.teams.get(team.id)
    await ctx.pixies.delete(b.id)

    assert after_a.leader_id == b.id
    assert (await ctx.teams.get(team.id)).leader_id is None


async def test_deleting_a_member_keeps_the_leader(ctx: AppContext) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA"))
    a, b = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B")]
    await ctx.pixies.update(a.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(b.id, UpdatePixie(team_id=team.id))
    after = await last_event(ctx)

    await ctx.pixies.delete(b.id)

    assert (await ctx.teams.get(team.id)).leader_id == a.id
    assert [t for t, _ in await events_since(ctx, after)] == [types.PIXIE_DELETED]


async def test_deleting_a_team_keeps_its_pixies_without_a_team(ctx: AppContext) -> None:
    team = await ctx.teams.create(CreateTeam(name="QA"))
    other = await ctx.teams.create(CreateTeam(name="Docs"))
    a, b, c = [await ctx.pixies.create(CreatePixie(name=n)) for n in ("A", "B", "C")]
    for pixie in (a, b):
        await ctx.pixies.update(pixie.id, UpdatePixie(team_id=team.id))
    await ctx.pixies.update(c.id, UpdatePixie(team_id=other.id))
    after = await last_event(ctx)

    await ctx.teams.delete(team.id)
    events = await events_since(ctx, after)

    assert [t.id for t in await ctx.teams.list_teams()] == [other.id]
    assert [(p.id, p.team_id) for p in await ctx.pixies.list_pixies()] == [
        (a.id, None),
        (b.id, None),
        (c.id, other.id),
    ]
    assert [t for t, _ in events] == [
        types.PIXIE_UPDATED,
        types.PIXIE_UPDATED,
        types.PIXIE_TEAM_DELETED,
    ]
    assert events[0][1]["pixie"]["team_id"] is None  # type: ignore[index]
    assert events[2][1] == {"id": team.id}


async def test_unknown_teams(ctx: AppContext) -> None:
    pixie = await ctx.pixies.create(CreatePixie(name="A"))

    with pytest.raises(TeamNotFoundError):
        await ctx.pixies.update(pixie.id, UpdatePixie(team_id="nope", name="Changed"))
    with pytest.raises(TeamNotFoundError):
        await ctx.teams.get("nope")
    with pytest.raises(TeamNotFoundError):
        await ctx.teams.update("nope", UpdateTeam(name="X"))
    with pytest.raises(TeamNotFoundError):
        await ctx.teams.delete("nope")
    # Nothing changed on the refused update.
    assert (await ctx.pixies.get(pixie.id)).name == "A"
