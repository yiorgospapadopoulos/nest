import keyring
import pytest

from harness.auth.secrets import SERVICE_NAME, KeychainSecretStore


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


def test_keychain_store_uses_the_harness_service(fake_keyring: MemoryKeyring) -> None:
    store = KeychainSecretStore()

    assert store.get("token") is None
    store.set("token", "s3cret")

    assert fake_keyring.values == {(SERVICE_NAME, "token"): "s3cret"}
    assert SERVICE_NAME == "harness"
    assert store.get("token") == "s3cret"
