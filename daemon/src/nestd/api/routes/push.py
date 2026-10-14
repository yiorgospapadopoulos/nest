"""Web push: the VAPID key, this device's subscriptions and a test notification."""

import base64
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Response, status
from pydantic import AfterValidator, BaseModel, StringConstraints

from nestd.api.deps import Context, RequireDevice
from nestd.auth.models import Device
from nestd.notifications.webpush import PushReport

router = APIRouter(prefix="/api/push")

Endpoint = Annotated[str, StringConstraints(pattern=r"^https://\S+$", max_length=2048)]

# The push services of Safari, Chrome, Firefox and Edge (H-05): the daemon posts signed
# requests to subscribed endpoints, so a subscription must not point anywhere else.
PUSH_SERVICE_HOSTS = (
    "web.push.apple.com",
    "fcm.googleapis.com",
    "updates.push.services.mozilla.com",
)
PUSH_SERVICE_DOMAINS = (".push.apple.com", ".notify.windows.com")


def _push_service(endpoint: str) -> str:
    parts = urlsplit(endpoint)
    host = (parts.hostname or "").lower()
    known = host in PUSH_SERVICE_HOSTS or host.endswith(PUSH_SERVICE_DOMAINS)
    if not known or parts.username is not None or parts.port not in (None, 443):
        msg = "not a known web push service"
        raise ValueError(msg)
    return endpoint


def _key_of_length(length: int, first: int | None = None) -> AfterValidator:
    def check(value: str) -> str:
        try:
            raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
        except ValueError as error:
            msg = "not base64url"
            raise ValueError(msg) from error
        if len(raw) != length or (first is not None and raw[0] != first):
            msg = f"expected a {length} byte key"
            raise ValueError(msg)
        return value

    return AfterValidator(check)


class SubscriptionKeys(BaseModel):
    # An uncompressed P-256 point and a 16 byte secret, as PushSubscription.toJSON() gives.
    p256dh: Annotated[str, _key_of_length(65, first=4)]
    auth: Annotated[str, _key_of_length(16)]


class SubscribeRequest(BaseModel):
    """`PushSubscription.toJSON()` from the browser; other fields are ignored."""

    endpoint: Annotated[Endpoint, AfterValidator(_push_service)]
    keys: SubscriptionKeys


class UnsubscribeRequest(BaseModel):
    endpoint: Endpoint


class VapidKey(BaseModel):
    public_key: str


@router.get("/vapid-key", dependencies=[RequireDevice])
async def vapid_key(ctx: Context) -> VapidKey:
    return VapidKey(public_key=ctx.notifications.keys.public_key())


@router.post("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(
    body: SubscribeRequest, ctx: Context, device: Annotated[Device, RequireDevice]
) -> Response:
    await ctx.notifications.subscriptions.upsert(
        device.id, body.endpoint, body.keys.p256dh, body.keys.auth
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe(
    body: UnsubscribeRequest, ctx: Context, device: Annotated[Device, RequireDevice]
) -> Response:
    """Idempotent: a subscription that is already gone is not an error."""
    await ctx.notifications.subscriptions.remove(device.id, body.endpoint)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test")
async def send_test(ctx: Context, device: Annotated[Device, RequireDevice]) -> PushReport:
    return await ctx.notifications.send_test(device.id)
