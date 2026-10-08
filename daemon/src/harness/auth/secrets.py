"""Secret storage. Secrets live only in the macOS Keychain."""

from typing import Protocol

import keyring

SERVICE_NAME = "harness"


class SecretStore(Protocol):
    def get(self, account: str) -> str | None: ...

    def set(self, account: str, value: str) -> None: ...


class KeychainSecretStore:
    def get(self, account: str) -> str | None:
        return keyring.get_password(SERVICE_NAME, account)

    def set(self, account: str, value: str) -> None:
        keyring.set_password(SERVICE_NAME, account, value)
