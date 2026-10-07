"""A fake push service and ntfy server on an httpx mock transport, and a push receiver."""

import base64
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field

import http_ece
import httpx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import JsonValue


def b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@dataclass
class Receiver:
    """A browser's push keys: it can read what was encrypted for it."""

    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    secret: bytes = field(default_factory=lambda: os.urandom(16))

    @property
    def p256dh(self) -> str:
        return b64(
            self.key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        )

    @property
    def auth(self) -> str:
        return b64(self.secret)

    def keys(self) -> dict[str, JsonValue]:
        return {"p256dh": self.p256dh, "auth": self.auth}

    def read(self, body: bytes) -> dict[str, JsonValue]:
        return json.loads(http_ece.decrypt(body, private_key=self.key, auth_secret=self.secret))


@dataclass
class FakeServers:
    """Answers 201 unless `statuses` says otherwise; `broken` URLs fail to connect."""

    statuses: dict[str, int] = field(default_factory=dict[str, int])
    broken: set[str] = field(default_factory=set[str])
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def to(self, url: str) -> list[httpx.Request]:
        return [request for request in self.requests if str(request.url) == url]

    def _handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in self.broken:
            raise httpx.ConnectError("unreachable", request=request)
        self.requests.append(request)
        return httpx.Response(self.statuses.get(url, 201))


def no_network() -> httpx.MockTransport:
    """For contexts whose tests must never deliver anything."""

    def refuse(request: httpx.Request) -> httpx.Response:
        msg = f"unexpected request to {request.url}"
        raise AssertionError(msg)

    return httpx.MockTransport(refuse)


def json_body(request: httpx.Request) -> Mapping[str, JsonValue]:
    return json.loads(request.content)
