"""Pixie teams: pixies called together with `@handle`, planned by their leader (B40)."""

from fastapi import APIRouter, Response, status

from harness.api.deps import Context, RequireDevice
from harness.pixies.models import CreateTeam, PixieTeam, UpdateTeam

router = APIRouter(prefix="/api/pixie-teams", dependencies=[RequireDevice])


@router.get("")
async def list_teams(ctx: Context) -> list[PixieTeam]:
    """In team order. A team's members are the pixies whose `team_id` is its id."""
    return await ctx.teams.list_teams()


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_team(body: CreateTeam, ctx: Context) -> PixieTeam:
    """Last in order, with no members and no leader. The handle shares the namespace of
    pixie slugs: 409 when taken, 422 when invalid or reserved.
    """
    return await ctx.teams.create(body)


@router.patch("/{team_id}")
async def update_team(team_id: str, body: UpdateTeam, ctx: Context) -> PixieTeam:
    """409 `leader_not_member` when `leader_id` is not one of the team's pixies."""
    return await ctx.teams.update(team_id, body)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_team(team_id: str, ctx: Context) -> Response:
    """Its pixies stay, without a team."""
    await ctx.teams.delete(team_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
