import logging

import keyring
import pytest
from keyring.errors import KeyringLocked, NoKeyringError, PasswordDeleteError, PasswordSetError

from nestd.auth.secrets import (
    LEGACY_SERVICE_NAME,
    SERVICE_NAME,
    KeyringSecretStore,
    SecretStoreUnavailableError,
)
from nestd.platform import LINUX


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value

    def delete_password(self, service: str, account: str) -> None:
        if self.values.pop((service, account), None) is None:
            raise PasswordDeleteError(account)


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    memory = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_password", memory.get_password)
    monkeypatch.setattr(keyring, "set_password", memory.set_password)
    monkeypatch.setattr(keyring, "delete_password", memory.delete_password)
    return memory


def test_keychain_store_uses_the_nest_service(fake_keyring: MemoryKeyring) -> None:
    store = KeyringSecretStore()

    assert store.get("token") is None
    store.set("token", "s3cret")

    assert fake_keyring.values == {(SERVICE_NAME, "token"): "s3cret"}
    assert SERVICE_NAME == "nest"
    assert store.get("token") == "s3cret"


def test_an_item_under_the_old_harness_service_is_copied_forward(
    fake_keyring: MemoryKeyring,
) -> None:
    """B43: a token saved before the rename is read once and written under `nest`; the old
    item stays."""
    fake_keyring.values[(LEGACY_SERVICE_NAME, "token")] = "old-s3cret"
    store = KeyringSecretStore()

    assert store.get("token") == "old-s3cret"

    assert fake_keyring.values == {
        (LEGACY_SERVICE_NAME, "token"): "old-s3cret",
        (SERVICE_NAME, "token"): "old-s3cret",
    }
    assert LEGACY_SERVICE_NAME == "harness"


def test_the_new_service_wins_over_the_old_one(fake_keyring: MemoryKeyring) -> None:
    fake_keyring.values[(LEGACY_SERVICE_NAME, "token")] = "old"
    fake_keyring.values[(SERVICE_NAME, "token")] = "new"

    assert KeyringSecretStore().get("token") == "new"
    assert fake_keyring.values[(LEGACY_SERVICE_NAME, "token")] == "old"


def test_a_failed_copy_forward_still_returns_the_old_secret(
    fake_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """B43: a locked keychain must not stop the daemon; the copy is tried again next time."""
    fake_keyring.values[(LEGACY_SERVICE_NAME, "token")] = "old-s3cret"

    def refuse(_service: str, _account: str, _value: str) -> None:
        raise PasswordSetError("Can't store password on keychain: (-60006, 'Unknown Error')")

    monkeypatch.setattr(keyring, "set_password", refuse)
    store = KeyringSecretStore()

    with caplog.at_level(logging.WARNING, logger="nestd.auth.secrets"):
        assert store.get("token") == "old-s3cret"

    assert [r.levelname for r in caplog.records] == ["WARNING"]
    assert "old-s3cret" not in caplog.text
    assert "token" in caplog.text
    assert fake_keyring.values == {(LEGACY_SERVICE_NAME, "token"): "old-s3cret"}
    # Writing a new secret still fails loudly.
    with pytest.raises(PasswordSetError):
        store.set("token", "new")


def test_an_item_is_deleted_and_a_missing_one_is_no_error(fake_keyring: MemoryKeyring) -> None:
    store = KeyringSecretStore()
    store.set("local-server:ls_1", "k")

    store.delete("local-server:ls_1")
    store.delete("local-server:ls_1")

    assert fake_keyring.values == {}


@pytest.mark.parametrize(
    "error",
    [
        NoKeyringError("No recommended backend was available."),
        KeyringLocked("Failed to unlock the collection!"),
    ],
)
def test_a_missing_or_locked_secret_service_says_what_to_do(
    fake_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    """B117: on Linux without a running, unlocked Secret Service the daemon cannot keep its
    token; it stops with what to do instead of a traceback."""

    def unavailable(*_args: str) -> None:
        raise error

    for name in ("get_password", "set_password", "delete_password"):
        monkeypatch.setattr(keyring, name, unavailable)
    store = KeyringSecretStore(LINUX.secret_store_help)

    for attempt in (
        lambda: store.get("token"),
        lambda: store.set("token", "s3cret"),
        lambda: store.delete("token"),
    ):
        with pytest.raises(SecretStoreUnavailableError) as caught:
            attempt()
        assert str(error) in str(caught.value)
        assert "install gnome-keyring" in str(caught.value).lower()
        assert "unlock the login keyring" in str(caught.value)
        assert "s3cret" not in str(caught.value)
