"""Outside clients' tokens (B151): made on request, kept in memory only as hashes, so a
restart or switching a client off drops them and nothing secret is stored (D180)."""

import hashlib
from secrets import token_urlsafe

from nestd.outside.models import ClientKind


class ClientTokens:
    def __init__(self) -> None:
        self._kinds: dict[str, ClientKind] = {}

    def issue(self, kind: ClientKind) -> str:
        token = token_urlsafe(32)
        self._kinds[_hash(token)] = kind
        return token

    def kind_of(self, token: str) -> ClientKind | None:
        return self._kinds.get(_hash(token))

    def drop(self, kind: ClientKind) -> None:
        self._kinds = {digest: owner for digest, owner in self._kinds.items() if owner != kind}


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()
