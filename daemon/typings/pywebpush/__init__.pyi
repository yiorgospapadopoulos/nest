# The parts of pywebpush that Nest uses; the package ships no type information.
from collections.abc import Mapping

class WebPushException(Exception): ...  # noqa: N818 (upstream name)

class WebPusher:
    def __init__(self, subscription_info: Mapping[str, object]) -> None: ...
    def encode(self, data: bytes, content_encoding: str = "aes128gcm") -> dict[str, bytes]: ...
