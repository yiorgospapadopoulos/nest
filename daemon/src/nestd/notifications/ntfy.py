"""Optional ntfy channel (https://ntfy.sh), off by default.

Anyone who knows a topic on a public server can read its messages, so the topic should be
long and random, or the server self-hosted. Messages are published as JSON to the server
root, which keeps non-ASCII titles intact (HTTP headers cannot carry them).
"""

import logging

import httpx

from nestd.config.models import NtfySettings
from nestd.notifications.messages import Notice

# ntfy priorities: 3 is the default, 4 is "high" (a longer vibration on phones).
_DEFAULT_PRIORITY = 3
_HIGH_PRIORITY = 4

logger = logging.getLogger(__name__)


class NtfyChannel:
    def __init__(self, http: httpx.AsyncClient) -> None:
        self._http = http

    async def send(self, notice: Notice, settings: NtfySettings) -> bool:
        """Publish the notice; True if the server accepted it."""
        if not settings.enabled or settings.topic is None:
            return False
        message: dict[str, str | int | list[str]] = {
            "topic": settings.topic,
            "title": notice.title,
            "message": notice.body,
            "priority": _HIGH_PRIORITY if notice.urgent else _DEFAULT_PRIORITY,
            "tags": [notice.kind],
        }
        if settings.click_base_url is not None:
            message["click"] = settings.click_base_url.rstrip("/") + notice.url
        server = settings.server.rstrip("/") + "/"
        try:
            response = await self._http.post(server, json=message)
        except httpx.HTTPError as error:
            logger.warning("ntfy delivery failed: %s", type(error).__name__)
            return False
        if not response.is_success:
            logger.warning("ntfy refused the message with HTTP %d", response.status_code)
            return False
        return True
