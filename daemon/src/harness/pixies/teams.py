"""Pixie teams: pixies called together with `@handle`, planned by their leader (B40).

The daemon keeps the leader rules: the first pixie to join an empty team leads it, and
when the leader leaves or is deleted the next member in pixie order takes over.
"""

from contextlib import suppress

from harness.events import types
from harness.events.bus import EventBus
from harness.pixies.errors import (
    DuplicateSlugError,
    LeaderNotMemberError,
    PixieNotFoundError,
)
from harness.pixies.models import CreateTeam, PixieTeam, UpdateTeam
from harness.pixies.slugs import check_slug, free_slug, slugify
from harness.pixies.store import PixieStore
from harness.pixies.team_store import TeamStore


class TeamService:
    def __init__(self, store: TeamStore, pixies: PixieStore, bus: EventBus) -> None:
        self._store = store
        self._pixies = pixies
        self._bus = bus

    async def list_teams(self) -> list[PixieTeam]:
        return await self._store.list_teams()

    async def get(self, team_id: str) -> PixieTeam:
        return await self._store.get(team_id)

    async def handles(self) -> set[str]:
        return await self._store.handles()

    async def create(self, request: CreateTeam) -> PixieTeam:
        slugs = await self._pixies.slugs()
        handle = request.handle or free_slug(
            slugify(request.name), slugs | await self._store.handles()
        )
        _check_handle(handle, slugs)
        team = await self._store.create(request.name, handle)
        await self._announce(team)
        return team

    async def update(self, team_id: str, request: UpdateTeam) -> PixieTeam:
        await self._store.get(team_id)
        changes = request.model_dump(exclude_none=True)
        if "handle" in changes:
            _check_handle(changes["handle"], await self._pixies.slugs())
        if "leader_id" in changes:
            await self._require_member(team_id, changes["leader_id"])
        team = await self._store.update(team_id, **changes)
        await self._announce(team)
        return team

    async def delete(self, team_id: str) -> None:
        """Its pixies stay, without a team: each is announced, then the team's end."""
        for pixie_id in await self._store.delete(team_id):
            pixie = await self._pixies.get(pixie_id)
            await self._bus.publish(types.PIXIE_UPDATED, {"pixie": pixie.model_dump(mode="json")})
        await self._bus.publish(types.PIXIE_TEAM_DELETED, {"id": team_id})

    async def member_moved(self, pixie_id: str, left: str | None, joined: str | None) -> None:
        """The pixie's `team_id` went from `left` to `joined`: keep both teams' leaders."""
        if left is not None:
            await self._hand_over(left)
        if joined is not None:
            team = await self._store.get(joined)
            if team.leader_id is None:
                await self._announce(await self._store.update(joined, leader_id=pixie_id))

    async def _hand_over(self, team_id: str) -> None:
        """A leader who is no longer a member gives way to the first member, or to none."""
        team = await self._store.get(team_id)
        members = [pixie.id for pixie in await self._pixies.members(team_id)]
        if team.leader_id in members:
            return
        leader = members[0] if members else None
        await self._announce(await self._store.update(team_id, leader_id=leader))

    async def _require_member(self, team_id: str, pixie_id: str) -> None:
        team_of: str | None = None
        with suppress(PixieNotFoundError):
            team_of = (await self._pixies.get(pixie_id)).team_id
        if team_of != team_id:
            msg = "the leader must be one of the team's pixies"
            raise LeaderNotMemberError(msg)

    async def _announce(self, team: PixieTeam) -> None:
        await self._bus.publish(types.PIXIE_TEAM_UPDATED, {"team": team.model_dump(mode="json")})


def _check_handle(handle: str, slugs: set[str]) -> None:
    check_slug(handle)
    if handle in slugs:
        msg = f"a pixie called @{handle} already exists"
        raise DuplicateSlugError(msg)
