# The parts of py-vapid that Nest uses; the package ships no type information.
from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey

class Vapid02:
    def __init__(
        self,
        private_key: EllipticCurvePrivateKey | None = None,
        conf: dict[str, object] | None = None,
    ) -> None: ...
    def sign(
        self, claims: dict[str, str | int], crypto_key: str | None = None
    ) -> dict[str, str]: ...
    @classmethod
    def verify(cls, auth: str) -> bool: ...
