"""Clients say when they are on screen, so the usage probe runs only while one is (D031)."""

from typing import Annotated

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict, Field

from nestd.api.deps import Context, RequireDevice
from nestd.auth.models import Device

router = APIRouter(prefix="/api/clients")


class VisibilityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    visible: bool
    # Tells apart several apps on one device, such as the Mac app and a browser.
    client: str = Field(default="app", pattern=r"^[A-Za-z0-9_-]{1,32}$")


@router.post("/visibility", status_code=status.HTTP_204_NO_CONTENT)
async def report_visibility(
    body: VisibilityReport, ctx: Context, device: Annotated[Device, RequireDevice]
) -> Response:
    """Send on show, on hide, and every minute while shown; a report lapses after 150 s."""
    refresher = ctx.usage_refresher
    if refresher.visibility.report(f"{device.id}/{body.client}", body.visible):
        refresher.wake()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
