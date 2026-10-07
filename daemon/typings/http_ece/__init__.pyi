# The parts of http-ece that the tests use to read encrypted pushes; untyped upstream.
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey

def decrypt(
    content: bytes,
    private_key: EllipticCurvePrivateKey | None = None,
    auth_secret: bytes | None = None,
    version: str = "aes128gcm",
) -> bytes: ...
