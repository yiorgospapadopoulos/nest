"""Which Nest is running (C19): its version and, from a source checkout, its git commit,
read once per process. Imported with the API, so `PROCESS_STARTED` is close to the
daemon process's own start."""

import subprocess
import time
from functools import cache
from pathlib import Path

from nestd import __version__
from nestd.paths import is_packaged
from nestd.perf.store import Build

PROCESS_STARTED = time.monotonic()
# daemon/src/nestd/perf/build.py: the checkout's daemon folder.
_SOURCE = Path(__file__).resolve().parents[3]


@cache
def current_build() -> Build:
    # A release has no commit, and on a clean Mac `git` would open Apple's install dialog.
    return Build(version=__version__, git_commit=None if is_packaged() else _commit(_SOURCE))


def _commit(folder: Path) -> str | None:
    """The short commit of the checkout `folder` is in; None when it is in none."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],  # noqa: S607
            cwd=folder,
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    commit = completed.stdout.strip()
    return commit if completed.returncode == 0 and commit else None


def ready_ms() -> int:
    """Milliseconds since the process started, as the daemon begins serving."""
    return round((time.monotonic() - PROCESS_STARTED) * 1000)
