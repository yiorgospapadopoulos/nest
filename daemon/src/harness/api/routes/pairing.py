import math

from fastapi import APIRouter, HTTPException, Response, status

from harness.api.deps import COOKIE_NAME, Context, RequireDevice
from harness.api.schemas import PairingCodeResponse, RedeemRequest, RedeemResponse
from harness.auth.devices import InvalidPairingCodeError, PairingLockedError
from harness.events import types

# 400 days, the longest lifetime browsers accept for a cookie.
COOKIE_MAX_AGE = 400 * 24 * 60 * 60

router = APIRouter(prefix="/api/pairing")


@router.post("/codes", dependencies=[RequireDevice])
async def create_code(ctx: Context) -> PairingCodeResponse:
    code = await ctx.devices.create_pairing_code()
    return PairingCodeResponse(code=code.code, expires_at=code.expires_at)


@router.post("/redeem")
async def redeem(body: RedeemRequest, response: Response, ctx: Context) -> RedeemResponse:
    try:
        device, token = await ctx.devices.redeem_pairing_code(body.code, body.device_name)
    except PairingLockedError as error:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many failed pairing attempts",
            headers={"Retry-After": str(math.ceil(error.retry_after.total_seconds()))},
        ) from error
    except InvalidPairingCodeError as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "invalid or expired pairing code"
        ) from error
    await ctx.bus.publish(types.DEVICE_PAIRED, {"device_id": device.id, "name": device.name})
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return RedeemResponse(device=device, token=token)
