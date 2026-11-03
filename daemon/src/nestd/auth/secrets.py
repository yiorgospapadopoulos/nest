"""Secret storage. Secrets live only in the system's own store: the Keychain on macOS,
the Secret Service on Linux."""

import logging
from collections.abc import Generator
from contextlib import contextmanager, suppress
from typing import Protocol

import keyring
from keyring.errors import (
    InitError,
    KeyringError,
    KeyringLocked,
    NoKeyringError,
    PasswordDeleteError,
)

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


class SecretStoreUnavailableError(Exception):
    """The system's secret store is missing or locked; the message says what to do."""


@contextmanager
def _available(help_text: str) -> Generator[None]:
    try:
        yield
    except (NoKeyringError, KeyringLocked, InitError) as error:
        msg = f"the secret store is not available ({error}). {help_text}".rstrip()
        raise SecretStoreUnavailableError(msg) from error


class KeyringSecretStore:
    """`help_text` says what to do when the system's store is missing or locked."""

    def __init__(self, help_text: str = "") -> None:
        self._help = help_text

    def get(self, account: str) -> str | None:
        with _available(self._help):
            return self._get(account)

    def set(self, account: str, value: str) -> None:
        with _available(self._help):
            keyring.set_password(SERVICE_NAME, account, value)

    def delete(self, account: str) -> None:
        with _available(self._help), suppress(PasswordDeleteError):
            keyring.delete_password(SERVICE_NAME, account)

    def _get(self, account: str) -> str | None:
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
                    "could not copy the secret %r from %r to %r: %s",
                    account,
                    LEGACY_SERVICE_NAME,
                    SERVICE_NAME,
                    error,
                )
        return legacy
