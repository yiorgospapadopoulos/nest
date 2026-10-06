from fastapi import APIRouter, HTTPException, Response, status

from harness.api.deps import Context, RequireDevice
from harness.auth.models import Device
from harness.events import types

router = APIRouter(prefix="/api/devices", dependencies=[RequireDevice])


@router.get("")
async def list_devices(ctx: Context) -> list[Device]:
    return await ctx.devices.list_devices()


@router.delete("/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(device_id: str, ctx: Context) -> Response:
    if not await ctx.devices.revoke(device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "unknown device")
    await ctx.bus.publish(types.DEVICE_REVOKED, {"device_id": device_id})
    return Response(status_code=status.HTTP_204_NO_CONTENT)
