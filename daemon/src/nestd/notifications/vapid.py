"""The VAPID key pair that identifies this daemon to web push services.

The private key lives only in the Keychain (PKCS#8 PEM); the public key is derived from it.
It is created on first use and must stay stable: subscriptions are bound to it.
"""

import base64
import logging
from datetime import datetime
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02

from nestd.auth.secrets import SecretStore

VAPID_ACCOUNT = "webpush-vapid-private"

logger = logging.getLogger(__name__)


class VapidKeys:
    def __init__(self, secrets: SecretStore) -> None:
        self._secrets = secrets
        self._key: ec.EllipticCurvePrivateKey | None = None

    def public_key(self) -> str:
        """The application server key for `PushManager.subscribe`, base64url without padding."""
        raw = (
            self._private()
            .public_key()
            .public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        )
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    def authorization(self, endpoint: str, subject: str, expires: datetime) -> str:
        """The `Authorization` header value for one push request to `endpoint`."""
        parts = urlsplit(endpoint)
        claims: dict[str, str | int] = {
            "sub": subject,
            "aud": f"{parts.scheme}://{parts.netloc}",
            "exp": int(expires.timestamp()),
        }
        return Vapid02(private_key=self._private()).sign(claims)["Authorization"]

    def _private(self) -> ec.EllipticCurvePrivateKey:
        if self._key is None:
            self._key = self._load() or self._create()
        return self._key

    def _load(self) -> ec.EllipticCurvePrivateKey | None:
        stored = self._secrets.get(VAPID_ACCOUNT)
        if stored is None:
            return None
        try:
            key = serialization.load_pem_private_key(stored.encode(), password=None)
        except ValueError:
            key = None
        if isinstance(key, ec.EllipticCurvePrivateKey) and isinstance(key.curve, ec.SECP256R1):
            return key
        logger.warning(
            "The stored web push key was unreadable; created a new one."
            " Each device must enable notifications again."
        )
        return None

    def _create(self) -> ec.EllipticCurvePrivateKey:
        key = ec.generate_private_key(ec.SECP256R1())
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        self._secrets.set(VAPID_ACCOUNT, pem.decode())
        return key
