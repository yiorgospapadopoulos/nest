"""One version across every part: a release built with two versions cannot update itself."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_part_holds_the_version_file() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "release" / "set_version.py"), "--check"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
