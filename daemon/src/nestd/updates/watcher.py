"""`python -m nestd.updates.watcher <port> <old> <new> <backup>`: outlives a relaunch.

Waits for the new daemon to answer with its version. If it never does, the service is
stopped, the database put back, `current` moved to the old version, the new one dropped, a
notice left, and the service started again. The database step is needed because the daemon
refuses a database newer than its code.

Run from the old version's folder in its own session (`app.start_watcher`), so it survives
the service's restart, and from the old version's code, which is known to work.
"""

import logging
import os
import shutil
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx

from nestd.paths import AppPaths
from nestd.platform import current_platform
from nestd.runtime import default_runtime
from nestd.service.base import ServiceManager
from nestd.service.manager import service_manager
from nestd.updates.app import point_current, read_state, save_state, starts_of
from nestd.updates.boot import TRIAL_SECONDS

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
# A new version that has started this often and still does not answer keeps crashing:
# going back then beats waiting out the time limit, which is for one that hangs.
CRASH_STARTS = 3
_HEALTH_LIMIT = 2.0


def version_on(port: int) -> str | None:
    """The version answering on `port`; None when nothing does."""
    try:
        response = httpx.get(
            f"http://127.0.0.1:{port}/api/health", timeout=_HEALTH_LIMIT, trust_env=False
        )
        version: object = response.json().get("version")
    except (httpx.HTTPError, ValueError, AttributeError):
        return None
    return version if isinstance(version, str) else None


@dataclass(frozen=True)
class Trial:
    paths: AppPaths
    service: ServiceManager
    port: int
    old: str
    new: str
    backup: Path
    version_on: Callable[[int], str | None] = version_on
    now: Callable[[], float] = time.monotonic
    pause: Callable[[float], None] = time.sleep
    seconds: float = TRIAL_SECONDS


def watch(trial: Trial) -> bool:
    """Whether the new version came up; when it did not, everything is put back."""
    deadline = trial.now() + trial.seconds
    daemon_dir = trial.paths.daemon_dir
    crashed = False
    while trial.now() < deadline:
        if trial.version_on(trial.port) == trial.new:
            logger.info("Nest %s answered; the update is confirmed", trial.new)
            _done(daemon_dir)
            return True
        if starts_of(daemon_dir, trial.new) >= CRASH_STARTS:
            logger.error("Nest %s started %d times without answering", trial.new, CRASH_STARTS)
            crashed = True
            break
        trial.pause(POLL_SECONDS)
    else:
        logger.error("Nest %s did not answer in time", trial.new)
    logger.error("going back to %s", trial.old)
    roll_back(trial, crashed=crashed)
    return False


def _done(daemon_dir: Path) -> None:
    state = read_state(daemon_dir)
    if state.updating is not None:
        save_state(daemon_dir, state.model_copy(update={"updating": None}))


def roll_back(trial: Trial, *, crashed: bool = False) -> None:
    daemon_dir = trial.paths.daemon_dir
    database = trial.paths.db_path
    trial.service.stop()
    for leftover in (f"{database.name}-wal", f"{database.name}-shm"):
        database.with_name(leftover).unlink(missing_ok=True)
    shutil.copy2(trial.backup, database)
    point_current(daemon_dir, trial.old)
    shutil.rmtree(daemon_dir / trial.new, ignore_errors=True)
    state = read_state(daemon_dir)
    # What happened, in the user's words (2026-11-07): a crash, or no answer at all.
    what = "kept crashing when it started" if crashed else "didn't respond when it started"
    notice = f"Nest {trial.new} {what}, so Nest went back to {trial.old}. Your chats are safe."
    update = {
        "previous": None,
        "previous_schema": None,
        "refused": [*state.refused, trial.new],
        "notice": notice,
        "updating": None,
    }
    save_state(daemon_dir, state.model_copy(update=update))
    trial.service.install()


def main(argv: Sequence[str]) -> int:
    port, old, new, backup = argv
    runtime = default_runtime()
    paths = AppPaths.from_env(runtime.env, runtime.home, current_platform())
    log = paths.logs_dir / "update.log"
    logging.basicConfig(filename=log, level=logging.INFO, format="%(asctime)s %(message)s")
    program = [str(paths.daemon_dir / "current" / "bin" / "python"), "-m", "nestd", "serve"]
    service = service_manager(
        runtime.platform,
        paths,
        runtime.home,
        runtime.env,
        os.getuid(),
        runtime.run_command,
        program,
    )
    return 0 if watch(Trial(paths, service, int(port), old, new, Path(backup))) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
