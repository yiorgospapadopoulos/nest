"""Release signatures (B155, D184): `latest.json` is signed with Nest's own release key and
the signature sits beside it in `latest.json.sig`, so a changed list of files, or a file that
no longer matches its sha256 in it, is refused before anything is installed.

The key is ECDSA P-256 with SHA-256, the strongest kind macOS's own `openssl` (LibreSSL) can
check, which `release/install.sh` relies on. The private key lives only in the release Mac's
Keychain (`release/release_key.py`). `release/install.sh` holds the same public keys.
"""

import base64
import hashlib
from collections.abc import Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key

from nestd.updates.build import PrepareError

SIGNATURE_SUFFIX = ".sig"

# Public keys, base64 DER. Signing uses the first; a release is accepted when any one of them
# signed it, so a new key can be added a release before it is used (see docs/development.md).
RELEASE_KEYS: tuple[str, ...] = (
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAEX8L6xEBnbhVD+ecB8PGYh6R8R3AwUAiH0NieeALPmlMt6oqrzgx0nR7ga/1DV974RmbmikaPw1Rj3/VbT5T9Rw==",
)


def fingerprint(key: str) -> str:
    """A short name for a public key, used to find its private key in the Keychain."""
    return hashlib.sha256(base64.b64decode(key)).hexdigest()[:16]


def _public_key(key: str) -> ec.EllipticCurvePublicKey:
    loaded = load_der_public_key(base64.b64decode(key))
    if not isinstance(loaded, ec.EllipticCurvePublicKey):
        msg = "a release key is not an ECDSA key"
        raise TypeError(msg)
    return loaded


def is_signed(manifest: bytes, signature: bytes, keys: Sequence[str] = RELEASE_KEYS) -> bool:
    for key in keys:
        try:
            _public_key(key).verify(signature, manifest, ec.ECDSA(hashes.SHA256()))
        except InvalidSignature:
            continue
        return True
    return False


def check_signature(
    address: str, manifest: bytes, signature: bytes | None, keys: Sequence[str] = RELEASE_KEYS
) -> None:
    """Raises PrepareError with what went wrong, for the log, unless one key signed it."""
    if signature is None:
        msg = f"the release at {address} has no signature, so its update was refused"
        raise PrepareError(msg)
    if not is_signed(manifest, signature, keys):
        msg = (
            f"the release at {address} is not signed by Nest's release key, so its update"
            " was refused. It may have been changed after it was published"
        )
        raise PrepareError(msg)
