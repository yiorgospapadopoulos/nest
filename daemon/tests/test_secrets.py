import logging

import keyring
import pytest
from keyring.errors import PasswordSetError

from nestd.auth.secrets import LEGACY_SERVICE_NAME, SERVICE_NAME, KeychainSecretStore


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, account: str) -> str | None:
        return self.values.get((service, account))

    def set_password(self, service: str, account: str, value: str) -> None:
        self.values[(service, account)] = value


@pytest.fixture
def fake_keyring(monkeypatch: pytest.MonkeyPatch) -> MemoryKeyring:
    memory = MemoryKeyring()
    monkeypatch.setattr(keyring, "get_password", memory.get_password)
    monkeypatch.setattr(keyring, "set_password", memory.set_password)
    return memory


def test_keychain_store_uses_the_nest_service(fake_keyring: MemoryKeyring) -> None:
    store = KeychainSecretStore()

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
    store = KeychainSecretStore()

    assert store.get("token") == "old-s3cret"

    assert fake_keyring.values == {
        (LEGACY_SERVICE_NAME, "token"): "old-s3cret",
        (SERVICE_NAME, "token"): "old-s3cret",
    }
    assert LEGACY_SERVICE_NAME == "harness"


def test_the_new_service_wins_over_the_old_one(fake_keyring: MemoryKeyring) -> None:
    fake_keyring.values[(LEGACY_SERVICE_NAME, "token")] = "old"
    fake_keyring.values[(SERVICE_NAME, "token")] = "new"

    assert KeychainSecretStore().get("token") == "new"
    assert fake_keyring.values[(LEGACY_SERVICE_NAME, "token")] == "old"


def test_a_failed_copy_forward_still_returns_the_old_secret(
    fake_keyring: MemoryKeyring, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """B43: a locked keychain must not stop the daemon; the copy is tried again next time."""
    fake_keyring.values[(LEGACY_SERVICE_NAME, "token")] = "old-s3cret"

    def refuse(_service: str, _account: str, _value: str) -> None:
        raise PasswordSetError("Can't store password on keychain: (-60006, 'Unknown Error')")

    monkeypatch.setattr(keyring, "set_password", refuse)
    store = KeychainSecretStore()

    with caplog.at_level(logging.WARNING, logger="nestd.auth.secrets"):
        assert store.get("token") == "old-s3cret"

    assert [r.levelname for r in caplog.records] == ["WARNING"]
    assert "old-s3cret" not in caplog.text
    assert "token" in caplog.text
    assert fake_keyring.values == {(LEGACY_SERVICE_NAME, "token"): "old-s3cret"}
    # Writing a new secret still fails loudly.
    with pytest.raises(PasswordSetError):
        store.set("token", "new")
