"""The release key's Keychain item trusts no app, so every read asks the user (B159 R14).

`security` and the Keychain are faked throughout: these tests never touch a real Keychain.
"""

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

SCRIPT = Path(__file__).resolve().parents[2] / "release" / "release_key.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("release_key", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeKeychain:
    """Stands in for both `security` and keyring's macOS backend."""

    def __init__(self) -> None:
        self.items: dict[str, bytes] = {}
        self.calls: list[list[str]] = []
        self.stdin: list[bytes] = []
        self.deleted: list[str] = []
        # How many `security -i` adds fail before one works.
        self.failing_adds = 0

    def run(self, args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        self.calls.append(args)
        if args[1] == "find-generic-password":
            found = args[args.index("-a") + 1] in self.items
            return subprocess.CompletedProcess(args, 0 if found else 44, b"", b"")
        assert args[1:] == ["-i"]
        data = kwargs["input"]
        assert isinstance(data, bytes)
        self.stdin.append(data)
        if self.failing_adds:
            self.failing_adds -= 1
            return subprocess.CompletedProcess(args, 1, b"", b"security: add failed")
        words = data.decode().split()
        self.items[words[words.index("-a") + 1]] = bytes.fromhex(words[words.index("-X") + 1])
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def keyring(self) -> "FakeKeychain":
        return self

    def get_password(self, service: str, name: str) -> str | None:
        stored = self.items.get(name)
        return None if stored is None else stored.decode()

    def delete_password(self, service: str, name: str) -> None:
        self.deleted.append(name)
        del self.items[name]

    def set_password(self, service: str, name: str, password: str) -> None:
        msg = "keyring's set_password trusts the calling Python"
        raise AssertionError(msg)


def _pem(private: ec.EllipticCurvePrivateKey) -> bytes:
    return private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )


@pytest.fixture
def keychain(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, FakeKeychain]:
    module = _load()
    fake = FakeKeychain()
    monkeypatch.setattr(module.subprocess, "run", fake.run)
    monkeypatch.setattr(module, "Keyring", fake.keyring)
    return module, fake


def _added(fake: FakeKeychain, private: ec.EllipticCurvePrivateKey) -> str:
    """The one `security -i` command, after checking the key is in no argv."""
    assert len(fake.stdin) == 1
    for args in fake.calls:
        assert not any(_pem(private).hex() in arg or "PRIVATE KEY" in arg for arg in args)
    return fake.stdin[0].decode()


def test_new_key_is_stored_with_no_trusted_app(
    keychain: tuple[ModuleType, FakeKeychain],
) -> None:
    module, fake = keychain
    module.new()

    (name,) = fake.items
    command = _added(fake, module.serialization.load_pem_private_key(fake.items[name], None))
    assert command.startswith(f'add-generic-password -s "Nest release key" -a {name} -T "" -X ')


def test_lock_resaves_the_existing_key_with_no_trusted_app(
    keychain: tuple[ModuleType, FakeKeychain], monkeypatch: pytest.MonkeyPatch
) -> None:
    module, fake = keychain
    private = ec.generate_private_key(ec.SECP256R1())
    public = module.public_of(private)
    name = module.fingerprint(public)
    monkeypatch.setattr(module, "RELEASE_KEYS", (public,))
    fake.items[name] = _pem(private)

    module.lock()

    assert fake.deleted == [name]
    assert ' -T "" ' in _added(fake, private)
    assert fake.items[name] == _pem(private)


@pytest.mark.parametrize("failing_adds", [1, 2])
def test_lock_puts_the_key_back_when_saving_it_again_fails(
    keychain: tuple[ModuleType, FakeKeychain], monkeypatch: pytest.MonkeyPatch, failing_adds: int
) -> None:
    # lock deletes the item before adding it again; the key in memory must not be lost.
    module, fake = keychain
    private = ec.generate_private_key(ec.SECP256R1())
    public = module.public_of(private)
    name = module.fingerprint(public)
    monkeypatch.setattr(module, "RELEASE_KEYS", (public,))
    fake.items[name] = _pem(private)
    fake.failing_adds = failing_adds

    if failing_adds == 1:
        module.lock()
        assert fake.items[name] == _pem(private)
    else:
        with pytest.raises(SystemExit, match=r"release_key\.py import"):
            module.lock()
