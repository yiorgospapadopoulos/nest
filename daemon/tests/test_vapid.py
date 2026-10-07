import base64
import json
import logging
from datetime import datetime

import pytest
from py_vapid import Vapid02

from harness.notifications.vapid import VAPID_ACCOUNT, VapidKeys
from tests.fakes import START, FakeSecretStore


def b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def claims(authorization: str) -> dict[str, str | int]:
    token = authorization.split("t=", 1)[1].split(",", 1)[0]
    return json.loads(b64decode(token.split(".")[1]))


def test_first_use_generates_and_stores_a_p256_key(secrets: FakeSecretStore) -> None:
    keys = VapidKeys(secrets)

    public = keys.public_key()

    raw = b64decode(public)
    assert len(raw) == 65
    assert raw[0] == 4
    assert "=" not in public
    stored = secrets.get(VAPID_ACCOUNT)
    assert stored is not None
    assert stored.startswith("-----BEGIN PRIVATE KEY-----")


def test_the_stored_key_is_reused(secrets: FakeSecretStore) -> None:
    first = VapidKeys(secrets).public_key()

    assert VapidKeys(secrets).public_key() == first


def test_authorization_is_a_valid_vapid_token_for_the_endpoint_origin(
    secrets: FakeSecretStore,
) -> None:
    keys = VapidKeys(secrets)
    expires = datetime.fromtimestamp(START.timestamp() + 3600, START.tzinfo)

    header = keys.authorization(
        "https://web.push.apple.com:443/QG/abc?x=1", "mailto:me@example.org", expires
    )

    assert header.startswith("vapid t=")
    assert header.endswith(f",k={keys.public_key()}")
    assert Vapid02.verify(header)
    assert claims(header) == {
        "sub": "mailto:me@example.org",
        "aud": "https://web.push.apple.com:443",
        "exp": int(expires.timestamp()),
    }


def test_an_unreadable_stored_key_is_replaced_with_a_warning(
    secrets: FakeSecretStore, caplog: pytest.LogCaptureFixture
) -> None:
    secrets.set(VAPID_ACCOUNT, "not a key")

    with caplog.at_level(logging.WARNING):
        public = VapidKeys(secrets).public_key()

    assert len(b64decode(public)) == 65
    assert secrets.get(VAPID_ACCOUNT) != "not a key"
    assert "enable notifications again" in caplog.text
    assert "not a key" not in caplog.text


def test_a_stored_key_of_another_curve_is_replaced(secrets: FakeSecretStore) -> None:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    other = ec.generate_private_key(ec.SECP384R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    secrets.set(VAPID_ACCOUNT, other.decode())

    assert len(b64decode(VapidKeys(secrets).public_key())) == 65
    assert secrets.get(VAPID_ACCOUNT) != other.decode()
