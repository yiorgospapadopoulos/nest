"""Secret storage. Secrets live only in the macOS Keychain."""

import logging
from contextlib import suppress
from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

logger = logging.getLogger(__name__)

SERVICE_NAME = "nest"
# The service before the rename to Nest (B43): read when `nest` has no item, then copied
# forward; the old item is left in place.
LEGACY_SERVICE_NAME = "harness"


class SecretStore(Protocol):
    def get(self, account: str) -> str | None: ...

    def set(self, account: str, value: str) -> None: ...

    def delete(self, account: str) -> None:
        """Remove the item; one that is not there is no error."""
        ...


class KeychainSecretStore:
    def get(self, account: str) -> str | None:
        value = keyring.get_password(SERVICE_NAME, account)
        if value is not None:
            return value
        legacy = keyring.get_password(LEGACY_SERVICE_NAME, account)
        if legacy is not None:
            # Best effort: a locked keychain must not stop the daemon; tried again next time.
            try:
                keyring.set_password(SERVICE_NAME, account, legacy)
            except KeyringError as error:
                logger.warning(
                    "could not copy the Keychain item %r from %r to %r: %s",
                    account,
                    LEGACY_SERVICE_NAME,
                    SERVICE_NAME,
                    error,
                )
        return legacy

    def set(self, account: str, value: str) -> None:
        keyring.set_password(SERVICE_NAME, account, value)

    def delete(self, account: str) -> None:
        with suppress(PasswordDeleteError):
            keyring.delete_password(SERVICE_NAME, account)
