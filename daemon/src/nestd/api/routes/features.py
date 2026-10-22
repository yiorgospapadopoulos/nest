from typing import Annotated

from fastapi import APIRouter
from pydantic import BaseModel, Field

from nestd.api.deps import Context, RequireDevice
from nestd.auth.models import Device
from nestd.features.service import FeaturesView

router = APIRouter(prefix="/api/features", dependencies=[RequireDevice])


class SeenRequest(BaseModel):
    ids: Annotated[list[str], Field(min_length=1, max_length=500)]


@router.get("")
async def list_features(ctx: Context, caller: Annotated[Device, RequireDevice]) -> FeaturesView:
    """Settings > Features (B103): the catalog by group, each feature marked new or not for
    the calling device, and how many are new."""
    return await ctx.features.view(caller.id)


@router.post("/seen")
async def features_seen(
    body: SeenRequest, ctx: Context, caller: Annotated[Device, RequireDevice]
) -> FeaturesView:
    """The calling device shows these features: records its first visit and when it first
    showed each one. Unknown ids are ignored."""
    return await ctx.features.mark_shown(caller.id, body.ids)
