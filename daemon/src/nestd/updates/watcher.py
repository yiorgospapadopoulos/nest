"""`python -m nestd.updates.watcher <port> <old> <new> <backup>`: outlives a relaunch.

Waits for the new daemon to answer with its version, then keeps counting its starts for a
while, as one that answers once and then crashes is no better. If it never answers, or keeps
crashing, the service is stopped, the database put back, `current` moved to the old version,
the new one dropped, a notice left, and the service started again. The database step is
needed because the daemon refuses a database newer than its code. Undo is watched the same
way, with the version it leaves as the old one.

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
from nestd.updates.app import Updating, point_current, read_state, save_state, starts_of
from nestd.updates.boot import TRIAL_SECONDS

logger = logging.getLogger(__name__)

POLL_SECONDS = 1.0
# A new version that has started this often and still does not answer keeps crashing:
# going back then beats waiting out the time limit, which is for one that hangs.
CRASH_STARTS = 3
# After its first answer, CRASH_STARTS more starts within this time count as crashing too
# (B159 R12): launchd restarts a crashed daemon about every 10 seconds. A start after a clean
# stop is no crash (`starts_of`).
SETTLE_SECONDS = 300.0
# How long the old daemon may take to exit after the service is stopped: launchd ends it by
# force after 20 seconds (B159 R13).
STOP_SECONDS = 30.0
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
    settle_seconds: float = SETTLE_SECONDS


def watch(trial: Trial) -> bool:
    """Whether the new version came up and stayed up; when not, everything is put back."""
    deadline = trial.now() + trial.seconds
    daemon_dir = trial.paths.daemon_dir
    # Read now: the first answer clears it, and a later rollback still needs its Undo.
    before = read_state(daemon_dir).updating
    crashed = answered = False
    while trial.now() < deadline:
        if trial.version_on(trial.port) == trial.new:
            logger.info("Nest %s answered", trial.new)
            _done(daemon_dir)
            if _settles(trial):
                logger.info("Nest %s kept running; the update is confirmed", trial.new)
                _done(daemon_dir, fallback=trial.old)
                return True
            crashed = answered = True
            break
        if starts_of(daemon_dir, trial.new) >= CRASH_STARTS:
            logger.error("Nest %s started %d times without answering", trial.new, CRASH_STARTS)
            crashed = True
            break
        trial.pause(POLL_SECONDS)
    else:
        logger.error("Nest %s did not answer in time", trial.new)
    logger.error("going back to %s", trial.old)
    roll_back(trial, before, crashed=crashed, answered=answered)
    return False


def _settles(trial: Trial) -> bool:
    """Whether the new version stops restarting for the settle time after it answered."""
    daemon_dir = trial.paths.daemon_dir
    first = starts_of(daemon_dir, trial.new)
    deadline = trial.now() + trial.settle_seconds
    while trial.now() < deadline:
        if starts_of(daemon_dir, trial.new) - first >= CRASH_STARTS:
            logger.error("Nest %s crashed %d times after it answered", trial.new, CRASH_STARTS)
            return False
        trial.pause(POLL_SECONDS)
    return True


def _wait_for_exit(trial: Trial) -> None:
    """`launchctl bootout` returns before the daemon has exited, and it may still write."""
    deadline = trial.now() + STOP_SECONDS
    while trial.service.status().loaded:
        if trial.now() >= deadline:
            logger.error("the old daemon is still running; putting the database back anyway")
            return
        trial.pause(POLL_SECONDS)


def _put_back(backup: Path, database: Path) -> None:
    """A new file renamed into place, so a daemon that still has the old one open cannot write
    into the restored one."""
    for leftover in (f"{database.name}-wal", f"{database.name}-shm"):
        database.with_name(leftover).unlink(missing_ok=True)
    restored = database.with_name(f".{database.name}.restoring")
    shutil.copy2(backup, restored)
    restored.replace(database)


def _done(daemon_dir: Path, *, fallback: str | None = None) -> None:
    """Clears the update under way, and once it is confirmed the version kept to go back to,
    unless an Undo since has kept another."""
    state = read_state(daemon_dir)
    update: dict[str, object] = {"updating": None}
    if fallback is not None and state.fallback == fallback:
        update["fallback"] = None
    if state.model_copy(update=update) != state:
        save_state(daemon_dir, state.model_copy(update=update))


def roll_back(
    trial: Trial, before: Updating | None, *, crashed: bool = False, answered: bool = False
) -> None:
    """`answered`: the new version ran for a while, so what was written since is lost."""
    daemon_dir = trial.paths.daemon_dir
    trial.service.stop()
    _wait_for_exit(trial)
    _put_back(trial.backup, trial.paths.db_path)
    point_current(daemon_dir, trial.old)
    shutil.rmtree(daemon_dir / trial.new, ignore_errors=True)
    state = read_state(daemon_dir)
    # What happened, in the user's words (2026-11-07): a crash, or no answer at all.
    what = "kept crashing when it started" if crashed else "didn't respond when it started"
    notice = f"Nest {trial.new} {what}, so Nest went back to {trial.old}. Your chats are safe."
    if answered:
        notice = (
            f"Nest {trial.new} kept crashing, so Nest went back to {trial.old} and to your chats"
            " as they were before the update. Anything done since the update is lost."
        )
    # The update is gone, so Undo goes back to what it went back to before it.
    update = {
        "previous": before.undo if before else None,
        "previous_schema": before.undo_schema if before else None,
        "refused": [*state.refused, trial.new],
        "notice": notice,
        "updating": None,
        "fallback": None,
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
