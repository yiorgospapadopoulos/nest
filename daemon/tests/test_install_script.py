"""`release/install.sh`'s promises: it never touches a developer's install, and a failure
leaves nothing half-installed. The machine and `uv` are stand-ins, the script is the real one.
"""

import hashlib
import json
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "release" / "install.sh"


def _write_program(path: Path, body: str) -> None:
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


@dataclass(frozen=True)
class Machine:
    home: Path
    data: Path
    release: Path
    env: dict[str, str]

    def run(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 (the repository's own script)
            ["/bin/sh", str(SCRIPT)],
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
    data = home / "data"
    env = {
        "HOME": str(home),
        "PATH": f"{shims}{os.pathsep}/usr/bin{os.pathsep}/bin",
        "NEST_DATA_DIR": str(data),
        "NEST_RELEASE_URL": f"file://{release}",
        "XDG_CONFIG_HOME": str(home / ".config"),
    }
    return Machine(home, data, release, env)


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
