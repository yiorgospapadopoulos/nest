"""`release/install.sh`'s promises: it never touches a developer's install, it trusts nothing
in a release that Nest's key did not sign, and a failure leaves nothing half-installed. The
machine and `uv` are stand-ins; the script is the real one, with a test key for Nest's.
"""

import base64
import hashlib
import json
import os
import re
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from nestd.updates.signature import RELEASE_KEYS

SCRIPT = Path(__file__).resolve().parents[2] / "release" / "install.sh"
_KEYS_LINE = re.compile(r'^RELEASE_KEYS="([^"]*)"$', re.MULTILINE)


def _public(key: ec.EllipticCurvePrivateKey) -> str:
    der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    return base64.b64encode(der).decode()


def _sign(key: ec.EllipticCurvePrivateKey, manifest: Path) -> bytes:
    return key.sign(manifest.read_bytes(), ec.ECDSA(hashes.SHA256()))


def _write_program(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@dataclass(frozen=True)
class Machine:
    home: Path
    data: Path
    release: Path
    env: dict[str, str]
    script: Path
    key: ec.EllipticCurvePrivateKey

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 (the repository's own script)
            ["/bin/sh", str(self.script)],
            capture_output=True,
            text=True,
            check=False,
            env=self.env,
            stdin=subprocess.DEVNULL,
            timeout=30,
        )


def _machine(tmp_path: Path, *, uv: str = "exit 0", app: bytes = b"app") -> Machine:
    """A Linux computer with a good release on disk, reached through `file://`."""
    home = tmp_path / "home"
    shims = tmp_path / "shims"
    release = tmp_path / "release"
    for folder in (home, shims, release):
        folder.mkdir()
    _write_program(shims / "uname", 'case "$1" in -s) echo Linux ;; *) echo x86_64 ;; esac')
    _write_program(shims / "systemctl", "exit 0")
    _write_program(shims / "uv", uv)
    files = {
        "Nest-1.0.0-linux-x86_64.AppImage": ("app", "linux-x86_64", app),
        "nestd-1.0.0-py3-none-any.whl": ("wheel", "any", b"wheel"),
        "nestd-1.0.0-requirements.txt": ("requirements", "any", b"requirements"),
    }
    lines: list[str] = []
    for name, (kind, platform, content) in files.items():
        (release / name).write_bytes(content)
        entry = {
            "platform": platform,
            "kind": kind,
            "name": name,
            "sha256": hashlib.sha256(content).hexdigest(),
        }
        lines.append("    " + json.dumps(entry))
    joined = ",\n".join(lines)
    latest = f'{{\n  "version": "1.0.0",\n  "notes": "",\n  "files": [\n{joined}\n  ]\n}}\n'
    (release / "latest.json").write_text(latest, encoding="utf-8")
    key = ec.generate_private_key(ec.SECP256R1())
    (release / "latest.json.sig").write_bytes(_sign(key, release / "latest.json"))
    script = tmp_path / "install.sh"
    text = SCRIPT.read_text(encoding="utf-8")
    script.write_text(_KEYS_LINE.sub(f'RELEASE_KEYS="{_public(key)}"', text), encoding="utf-8")
    data = home / "data"
    env = {
        "HOME": str(home),
        "PATH": f"{shims}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "NEST_DATA_DIR": str(data),
        "NEST_RELEASE_URL": f"file://{release}",
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    return Machine(home, data, release, env, script, key)


def test_the_script_trusts_the_same_keys_as_the_daemon() -> None:
    found = _KEYS_LINE.search(SCRIPT.read_text(encoding="utf-8"))

    assert found is not None
    assert found[1].split() == list(RELEASE_KEYS)


def _no_signature(machine: Machine) -> None:
    (machine.release / "latest.json.sig").unlink()


def _signed_by_another_key(machine: Machine) -> None:
    other = ec.generate_private_key(ec.SECP256R1())
    (machine.release / "latest.json.sig").write_bytes(_sign(other, machine.release / "latest.json"))


def _changed_after_signing(machine: Machine) -> None:
    # A swapped wheel with its sha256 changed to match: only the signature catches it.
    wheel = machine.release / "nestd-1.0.0-py3-none-any.whl"
    latest = machine.release / "latest.json"
    old = hashlib.sha256(wheel.read_bytes()).hexdigest()
    wheel.write_bytes(b"not the wheel")
    new = hashlib.sha256(b"not the wheel").hexdigest()
    latest.write_text(latest.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (_no_signature, "This release has no signature"),
        (_signed_by_another_key, "isn't signed by Nest's release key"),
        (_changed_after_signing, "isn't signed by Nest's release key"),
    ],
)
def test_a_release_not_signed_by_nests_key_installs_nothing(
    tmp_path: Path, tamper: Callable[[Machine], None], message: str
) -> None:
    machine = _machine(tmp_path, uv=_BUILDING_UV, app=_UNPACKING_APP)
    tamper(machine)

    result = machine.run()

    assert result.returncode == 1
    assert message in result.stderr
    assert "Installing Nest" not in result.stdout
    assert not machine.data.exists()


def test_a_developer_install_stops_it_before_anything_changes(tmp_path: Path) -> None:
    machine = _machine(tmp_path)
    unit = machine.home / ".config" / "systemd" / "user" / "nest.service"
    unit.parent.mkdir(parents=True)
    original = 'ExecStart="/home/me/nest/daemon/.venv/bin/python" "-m" "nestd" "serve"\n'
    unit.write_text(original, encoding="utf-8")

    result = machine.run()

    assert result.returncode == 1
    assert "already runs from somewhere else" in result.stderr
    assert unit.read_text(encoding="utf-8") == original
    assert not machine.data.exists()


def test_a_service_of_its_own_is_a_repair_not_a_developer_install(tmp_path: Path) -> None:
    machine = _machine(tmp_path, uv="exit 3")
    unit = machine.home / ".config" / "systemd" / "user" / "nest.service"
    unit.parent.mkdir(parents=True)
    python = machine.data / "daemon" / "current" / "bin" / "python"
    unit.write_text(f'ExecStart="{python}" "-m" "nestd" "serve"\n', encoding="utf-8")

    result = machine.run()

    assert "already runs from somewhere else" not in result.stderr


def test_a_bad_checksum_leaves_nothing_behind(tmp_path: Path) -> None:
    machine = _machine(tmp_path)
    (machine.release / "nestd-1.0.0-py3-none-any.whl").write_bytes(b"not the wheel")

    result = machine.run()

    assert result.returncode == 1
    assert "didn't match its checksum" in result.stderr
    assert not machine.data.exists()


def test_a_daemon_that_cannot_be_built_leaves_no_half_made_folder(tmp_path: Path) -> None:
    machine = _machine(tmp_path, uv='case "$1" in venv) exit 0 ;; *) exit 3 ;; esac')

    result = machine.run()

    assert result.returncode != 0
    assert list((machine.data / "daemon").iterdir()) == []
    assert not (machine.data / "app").exists()
    assert not (machine.home / ".local").exists()


# A uv that makes a venv whose python answers everything, and an AppImage that unpacks.
_BUILDING_UV = 'case "$1" in venv) for last; do :; done; mkdir -p "$last/bin"; ' + (
    'printf \'#!/bin/sh\\nexit 0\\n\' > "$last/bin/python"; chmod +x "$last/bin/python" ;; esac'
)
_UNPACKING_APP = b"#!/bin/sh\nmkdir -p squashfs-root/usr/share/icons/hicolor\n"


def test_a_secret_service_that_never_answers_says_so(tmp_path: Path) -> None:
    # On 2026-11-08 a new keyring's password window made this stop with only "Fix that".
    machine = _machine(tmp_path, uv=_BUILDING_UV, app=_UNPACKING_APP)
    _write_program(Path(machine.env["PATH"].split(os.pathsep)[0]) / "timeout", "exit 124")

    result = machine.run()

    assert result.returncode == 1
    assert "The Secret Service didn't answer" in result.stderr
