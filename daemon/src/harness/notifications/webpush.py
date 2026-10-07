"""Web push delivery (RFC 8030) with aes128gcm payloads and VAPID authentication."""

import asyncio
import json
import logging
from datetime import timedelta
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel
from pywebpush import WebPusher, WebPushException

from harness.clock import Clock
from harness.notifications.messages import Notice
from harness.notifications.subscriptions import PushSubscription, PushSubscriptionStore
from harness.notifications.vapid import VapidKeys

# A phone that is off or asleep still gets the notification within a day.
TTL_SECONDS = 24 * 60 * 60
TOKEN_LIFETIME = timedelta(hours=1)
# The push service no longer knows the subscription: the browser unsubscribed or expired it.
_GONE = frozenset({404, 410})

type _Outcome = Literal["sent", "failed", "removed"]

logger = logging.getLogger(__name__)


class PushReport(BaseModel):
    sent: int = 0
    failed: int = 0
    removed: int = 0


class WebPushChannel:
    def __init__(
        self, store: PushSubscriptionStore, keys: VapidKeys, clock: Clock, http: httpx.AsyncClient
    ) -> None:
        self._store = store
        self._keys = keys
        self._clock = clock
        self._http = http

    async def send(
        self, notice: Notice, subscriptions: list[PushSubscription], subject: str
    ) -> PushReport:
        outcomes = await asyncio.gather(
            *(self._send_one(notice, sub, subject) for sub in subscriptions)
        )
        return PushReport(
            sent=outcomes.count("sent"),
            failed=outcomes.count("failed"),
            removed=outcomes.count("removed"),
        )

    async def _send_one(self, notice: Notice, sub: PushSubscription, subject: str) -> _Outcome:
        # The endpoint path is a capability URL, so only its host is ever logged.
        host = urlsplit(sub.endpoint).hostname
        try:
            body = WebPusher(
                {"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}}
            ).encode(json.dumps(notice.web_payload()).encode())["body"]
        except (WebPushException, ValueError):
            logger.warning("Web push to %s skipped: the subscription keys are unusable", host)
            await self._store.failed(sub.id)
            return "failed"
        headers = {
            "TTL": str(TTL_SECONDS),
            "Urgency": "high" if notice.urgent else "normal",
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "Authorization": self._keys.authorization(
                sub.endpoint, subject, self._clock.now() + TOKEN_LIFETIME
            ),
        }
        try:
            response = await self._http.post(sub.endpoint, content=body, headers=headers)
        except httpx.HTTPError as error:
            logger.warning("Web push to %s failed: %s", host, type(error).__name__)
            await self._store.failed(sub.id)
            return "failed"
        if response.is_success:
            await self._store.succeeded(sub.id)
            return "sent"
        if response.status_code in _GONE:
            await self._store.delete(sub.id)
            return "removed"
        logger.warning(
            "Web push to %s was refused with HTTP %d: %s",
            host,
            response.status_code,
            response.text[:200],
        )
        await self._store.failed(sub.id)
        return "failed"
