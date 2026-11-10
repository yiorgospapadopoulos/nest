"""`make release` signs and ships what is on disk, and the public repository gets the
committed files only, so a release is built from committed code alone (B159 R54).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "release" / "check_clean.sh"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)  # noqa: S603, S607


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "release").mkdir()
    shutil.copy(SCRIPT, tmp_path / "release" / "check_clean.sh")
    (tmp_path / "daemon").mkdir()
    (tmp_path / "daemon" / "app.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start")
    return tmp_path


def _check(repo: Path, allow_dirty: bool = False) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.pop("NEST_RELEASE_ALLOW_DIRTY", None)
    if allow_dirty:
        env["NEST_RELEASE_ALLOW_DIRTY"] = "1"
    return subprocess.run(  # noqa: S603 (the repository's own script)
        ["bash", str(repo / "release" / "check_clean.sh")],  # noqa: S607
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_a_committed_tree_builds(repo: Path) -> None:
    (repo / "plans").mkdir()
    (repo / "plans" / "notes.md").write_text("scratch\n", encoding="utf-8")

    result = _check(repo)

    assert result.returncode == 0
    assert result.stdout.strip() == "clean"


@pytest.mark.parametrize("change", ["edited", "untracked in the build"])
def test_uncommitted_code_stops_the_release(repo: Path, change: str) -> None:
    if change == "edited":
        (repo / "daemon" / "app.py").write_text("x = 2\n", encoding="utf-8")
    else:
        (repo / "daemon" / "new.py").write_text("y = 1\n", encoding="utf-8")

    refused = _check(repo)
    allowed = _check(repo, allow_dirty=True)

    assert refused.returncode == 1
    assert "daemon/" in refused.stderr
    assert "NEST_RELEASE_ALLOW_DIRTY" in refused.stderr
    assert allowed.returncode == 0
    assert allowed.stdout.strip() == "dirty"


def test_an_ignored_file_in_the_shipped_code_stops_the_release(repo: Path) -> None:
    # The wheel backend packs everything under daemon/src, .gitignore or not.
    (repo / ".gitignore").write_text(".env\n__pycache__/\n", encoding="utf-8")
    _git(repo, "add", ".gitignore")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "ignore")
    package = repo / "daemon" / "src" / "nestd"
    (package / "__pycache__").mkdir(parents=True)
    (package / "__pycache__" / "app.cpython-312.pyc").write_bytes(b"cache")
    assert _check(repo).returncode == 0

    (package / ".env").write_text("TOKEN=secret\n", encoding="utf-8")
    refused = _check(repo)

    assert refused.returncode == 1
    assert "daemon/src/nestd/.env" in refused.stderr
