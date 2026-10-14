import math
from ipaddress import ip_address

from fastapi import APIRouter, HTTPException, Request, Response, status

from nestd.api.deps import COOKIE_NAME, Context, RequireDevice
from nestd.api.schemas import PairingCodeResponse, RedeemRequest, RedeemResponse
from nestd.auth.devices import InvalidPairingCodeError, PairingLockedError

# 400 days, the longest lifetime browsers accept for a cookie.
COOKIE_MAX_AGE = 400 * 24 * 60 * 60

router = APIRouter(prefix="/api/pairing")


@router.post("/codes", dependencies=[RequireDevice])
async def create_code(ctx: Context) -> PairingCodeResponse:
    code = await ctx.devices.create_pairing_code()
    return PairingCodeResponse(code=code.code, expires_at=code.expires_at)


@router.post("/redeem")
async def redeem(
    body: RedeemRequest, request: Request, response: Response, ctx: Context
) -> RedeemResponse:
    try:
        device, token = await ctx.devices.redeem_pairing_code(
            body.code, body.device_name, client=client_address(request)
        )
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
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return RedeemResponse(device=device, token=token)


def client_address(request: Request) -> str:
    """The address failed pairing attempts count against (H-01).

    The daemon listens on 127.0.0.1 only, so the iPhone arrives through `tailscale serve`,
    which connects from loopback and sets X-Forwarded-For to the phone's tailnet address,
    replacing whatever the client sent. Only the last entry is taken, so a header with
    several entries counts as its last one. A local process can also send the header, so
    the device service keeps a global limit as well.
    """
    peer = request.client.host if request.client is not None else None
    if peer is None:
        return "unknown"
    if _is_loopback(peer):
        forwarded = request.headers.get("x-forwarded-for", "").split(",")[-1].strip()
        if forwarded:
            return forwarded
    return peer


def _is_loopback(host: str) -> bool:
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False
