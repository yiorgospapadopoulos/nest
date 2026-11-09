"""Nest's release key (B155, D184): kept in the release Mac's login Keychain, never in a file,
with a backup the user keeps in a password manager. `make_manifest.py` signs `latest.json`.

    release_key.py new            makes a key and prints its public key for RELEASE_KEYS
    release_key.py public         prints RELEASE_KEYS and which of them this Keychain holds
    release_key.py check          stops unless this Keychain can sign a release
    release_key.py export         copies the signing key to the clipboard, for a backup
    release_key.py import         puts a trusted key from the clipboard into this Keychain
    release_key.py check-backup   says whether the clipboard holds a trusted key

Each key is a Keychain password named "Nest release key", its account the key's fingerprint,
so signing finds the private key of the first of the daemon's RELEASE_KEYS. A backup is the
key as one line of base64 (PKCS8 DER), short enough for a password field. The key only ever
passes through the clipboard, never the screen, and `import` and `check-backup` clear it.
"""

import base64
import binascii
import subprocess
import sys

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from keyring.backends.macOS import Keyring

from nestd.updates.signature import RELEASE_KEYS, fingerprint, is_signed

SERVICE = "Nest release key"


def public_of(private: ec.EllipticCurvePrivateKey) -> str:
    der = private.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der).decode()


def _pem(private: ec.EllipticCurvePrivateKey) -> str:
    return private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()


def _stored(name: str) -> ec.EllipticCurvePrivateKey | None:
    pem = Keyring().get_password(SERVICE, name)
    if pem is None:
        return None
    private = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(private, ec.EllipticCurvePrivateKey):
        msg = f'the Keychain item "{SERVICE}" for {name} is not an ECDSA key'
        raise SystemExit(msg)
    return private


def _store(private: ec.EllipticCurvePrivateKey) -> str:
    name = fingerprint(public_of(private))
    Keyring().set_password(SERVICE, name, _pem(private))  # pyright: ignore[reportUnknownMemberType]
    return name


def _signing_key() -> ec.EllipticCurvePrivateKey:
    private = _stored(fingerprint(RELEASE_KEYS[0]))
    if private is None:
        msg = (
            f"release: the Keychain has no release key for {fingerprint(RELEASE_KEYS[0])}. "
            "Run `release_key.py import` with the backup, or see docs/development.md"
        )
        raise SystemExit(msg)
    return private


def _copy(text: str) -> None:
    subprocess.run(["/usr/bin/pbcopy"], input=text.encode(), check=True)


def _paste() -> str:
    return subprocess.run(["/usr/bin/pbpaste"], capture_output=True, check=True).stdout.decode()


def _trusted_from_clipboard() -> ec.EllipticCurvePrivateKey:
    """The key on the clipboard, which is then cleared; stops unless Nest trusts it."""
    text = _paste().strip()
    _copy("")
    try:
        private = serialization.load_der_private_key(base64.b64decode(text), password=None)
    except (ValueError, TypeError, binascii.Error, UnsupportedAlgorithm):
        msg = "The clipboard doesn't hold a release key. Copy the backup again, then retry."
        raise SystemExit(msg) from None
    if (
        not isinstance(private, ec.EllipticCurvePrivateKey)
        or public_of(private) not in RELEASE_KEYS
    ):
        msg = "The clipboard holds a key, but not one of Nest's RELEASE_KEYS."
        raise SystemExit(msg)
    return private


def sign(manifest: bytes) -> bytes:
    """The signature of the first trusted key, checked against every trusted key."""
    signature = _signing_key().sign(manifest, ec.ECDSA(hashes.SHA256()))
    if not is_signed(manifest, signature):
        msg = "release: the Keychain's release key does not match RELEASE_KEYS"
        raise SystemExit(msg)
    return signature


def new() -> None:
    private = ec.generate_private_key(ec.SECP256R1())
    name = _store(private)
    print(f"Made the release key {name}. Its public key, for RELEASE_KEYS:")
    print(public_of(private))


def public() -> None:
    for key in RELEASE_KEYS:
        found = "in this Keychain" if _stored(fingerprint(key)) else "not in this Keychain"
        print(f"{fingerprint(key)} ({found}): {key}")


def check() -> None:
    sign(b"")


def export() -> None:
    private = _signing_key()
    der = private.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    _copy(base64.b64encode(der).decode())
    print(f"Copied the release key {fingerprint(RELEASE_KEYS[0])} to the clipboard.")
    print("Paste it into the password field of your backup entry, then run")
    print("`release_key.py check-backup` with the backup copied, which also clears the clipboard.")


def import_() -> None:
    private = _trusted_from_clipboard()
    print(f"Put the release key {_store(private)} in this Keychain. The clipboard is cleared.")


def check_backup() -> None:
    private = _trusted_from_clipboard()
    name = fingerprint(public_of(private))
    print(f"The backup is the release key {name}, which Nest trusts. The clipboard is cleared.")


def main() -> int:
    commands = {
        "new": new,
        "public": public,
        "check": check,
        "export": export,
        "import": import_,
        "check-backup": check_backup,
    }
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        print(__doc__, file=sys.stderr)
        return 2
    commands[sys.argv[1]]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
