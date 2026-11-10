"""`release/install.sh`'s promises: it never touches a developer's install, it trusts nothing
in a release that Nest's key did not sign, and a failure leaves nothing half-installed. The
machine and `uv` are stand-ins; the script is the real one, with a test key for Nest's.
"""

import base64
import hashlib
import json
import os
import re
import sqlite3
import stat
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
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


@pytest.mark.parametrize(
    ("version", "refused"),
    [("15.0", False), ("26.1", False), ("14.7.1", True)],
)
def test_a_mac_needs_macos_15_or_later(tmp_path: Path, version: str, refused: bool) -> None:
    # B158: the Mac app runs on macOS 15 and later. The test release has no Mac app, so an
    # accepted Mac stops at that, before anything changes.
    machine = _machine(tmp_path)
    shims = Path(machine.env["PATH"].split(os.pathsep)[0])
    _write_program(shims / "uname", 'case "$1" in -s) echo Darwin ;; *) echo arm64 ;; esac')
    _write_program(shims / "sysctl", "echo 1")
    _write_program(shims / "sw_vers", f"echo {version}")
    for program in ("launchctl", "open"):
        _write_program(shims / program, "exit 1")
    (tmp_path / "Applications").mkdir()
    env = {**machine.env, "NEST_MAC_APP": str(tmp_path / "Applications" / "Nest.app")}

    result = subprocess.run(  # noqa: S603 (the repository's own script)
        ["/bin/sh", str(machine.script)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        stdin=subprocess.DEVNULL,
        timeout=30,
    )

    assert result.returncode == 1
    needs = f"Nest needs macOS 15 or later. This Mac has {version}."
    assert (needs in result.stderr) is refused
    if not refused:
        assert "This release has no app for macos-arm64." in result.stderr
    assert not machine.data.exists()


def _installed(machine: Machine, version: str) -> Path:
    """A released install of `version` with a database, as the install line left it."""
    folder = machine.data / "daemon" / version
    folder.mkdir(parents=True)
    (machine.data / "daemon" / "current").symlink_to(version)
    database = machine.data / "nest.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE t (value TEXT)")
    connection.execute("INSERT INTO t VALUES ('my chats')")
    connection.execute("PRAGMA user_version = 47")
    connection.commit()
    connection.close()
    return database


# A uv whose venv python runs real Python for `-c` (the backup) and answers the rest.
_BACKING_UP_UV = 'case "$1" in venv) for last; do :; done; mkdir -p "$last/bin"; ' + (
    'printf \'#!/bin/sh\\n[ "$1" = -c ] && exec "%s" "$@"\\nexit 0\\n\' '
    f'"{sys.executable}" > "$last/bin/python"; chmod +x "$last/bin/python" ;; esac'
)


def test_an_older_release_is_refused_over_a_newer_install(tmp_path: Path) -> None:
    # B159 R11: a pulled release put an older Nest over a database it cannot read.
    machine = _machine(tmp_path, uv=_BACKING_UP_UV, app=_UNPACKING_APP)
    _installed(machine, "2.0.0")

    result = machine.run()

    assert result.returncode == 1
    assert "Nest 2.0.0 is installed" in result.stderr
    assert "NEST_ALLOW_DOWNGRADE=1" in result.stderr
    assert (machine.data / "daemon" / "current").resolve().name == "2.0.0"
    assert sorted(entry.name for entry in (machine.data / "daemon").iterdir()) == [
        "2.0.0",
        "current",
    ]


@pytest.mark.parametrize(("installed", "forced"), [("0.9.0", False), ("2.0.0", True)])
def test_the_database_is_backed_up_before_current_moves(
    tmp_path: Path, installed: str, forced: bool
) -> None:
    # B159 R11: installing over another version migrated the database with no backup.
    machine = _machine(tmp_path, uv=_BACKING_UP_UV, app=_UNPACKING_APP)
    _installed(machine, installed)
    env = {**machine.env, **({"NEST_ALLOW_DOWNGRADE": "1"} if forced else {})}

    result = replace(machine, env=env).run()

    assert result.returncode == 0, result.stderr
    backup = machine.data / "backups-update" / "nest.db.before-install-1.0.0"
    assert str(backup) in result.stdout
    connection = sqlite3.connect(backup)
    assert connection.execute("SELECT value FROM t").fetchone() == ("my chats",)
    assert connection.execute("PRAGMA user_version").fetchone() == (47,)
    connection.close()
    assert (machine.data / "daemon" / "current").resolve().name == "1.0.0"


def test_running_the_install_line_again_keeps_the_first_backup_and_makes_another(
    tmp_path: Path,
) -> None:
    # B159 recheck 1: a repair with the same version replaced the backup with the migrated data.
    # Recheck 2 E: a forced downgrade to a version installed long ago backed up nothing.
    machine = _machine(tmp_path, uv=_BACKING_UP_UV, app=_UNPACKING_APP)
    database = _installed(machine, "0.9.0")
    assert machine.run().returncode == 0
    connection = sqlite3.connect(database)
    connection.execute("UPDATE t SET value = 'migrated'")
    connection.commit()
    connection.close()

    again = machine.run()

    assert again.returncode == 0, again.stderr
    backups = machine.data / "backups-update"
    first = backups / "nest.db.before-install-1.0.0"
    [later] = sorted(backups.glob("nest.db.before-install-1.0.0-*"))
    assert str(later) in again.stdout
    for backup, value in ((first, "my chats"), (later, "migrated")):
        connection = sqlite3.connect(backup)
        assert connection.execute("SELECT value FROM t").fetchone() == (value,)
        connection.close()
