"""The switch at the very start of `nestd serve`.

The service files always start the base environment, which is never changed, so the first
process is known good. It reads the state and, when an environment should run, replaces
itself with that environment's Python: same PID, so launchd and systemd notice nothing.

Every boot of an environment has to prove itself. The base counts it before handing over,
and the daemon clears the count once its own `/api/health` answers, so a restart after a
good boot starts from nothing. A base that finds the count at the limit leaves that
environment for the previous one: one boot for an update never confirmed yet, `BOOT_LIMIT`
in a row for one that once worked, which something since broke (a deploy that changes the
code but no package, for one). The previous one is held to the same count, so a crash loop
always ends on the base. A daemon that hangs before confirming is ended by `TrialWatch`, so
the service manager starts the base and the boot counts like a crash.

Nothing here may stop the daemon: whatever goes wrong, it runs on the base and logs.
"""

import hashlib
import logging
import os
import site
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

from nestd.updates.environments import python_of, running_environment, usable
from nestd.updates.manifest import read_manifest
from nestd.updates.state import BASE, StateFile, UpdateState, boot_limit, rolled_back

logger = logging.getLogger(__name__)

# Set for the replaced process, which drops it, so nothing it starts inherits it: a process
# that has it never switches again, should Python report another prefix than expected.
SWITCHED_ENV = "NEST_ENVIRONMENT_SWITCHED"
# How long a daemon in an environment has to answer its own health check.
TRIAL_SECONDS = 120.0

# Replaces this process: the program, its arguments and its environment.
type ExecProgram = Callable[[str, list[str], Mapping[str, str]], None]


def exec_program(program: str, args: list[str], env: Mapping[str, str]) -> None:
    os.execve(program, args, env)  # noqa: S606 (Nest's own environment, a fixed command)


def installed_fingerprint() -> str:
    """The environment this process runs in: every package at its version, sorted."""
    entries = {
        f"{dist.name}=={dist.version}".lower()
        for dist in metadata.distributions(path=site.getsitepackages())
    }
    return hashlib.sha256("\n".join(sorted(entries)).encode()).hexdigest()


class TrialWatch:
    """Ends the process unless the boot is confirmed in time."""

    def __init__(
        self, seconds: float = TRIAL_SECONDS, end: Callable[[int], None] = os._exit
    ) -> None:
        self._seconds = seconds
        self._end = end
        self._confirmed = threading.Event()
        self._thread = threading.Thread(target=self._wait, name="nest-trial", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def confirm(self) -> None:
        self._confirmed.set()

    def _wait(self) -> None:
        if not self._confirmed.wait(self._seconds):
            logger.error("the daemon did not confirm in time; ending it so it counts")
            self._end(1)


@dataclass(frozen=True)
class Boot:
    # `<data_dir>/environments`.
    root: Path
    # This process's `sys.prefix` and `sys.executable`.
    prefix: Path
    executable: str
    env: Mapping[str, str]
    exec_program: ExecProgram
    fingerprint: Callable[[], str] = installed_fingerprint
    watch: Callable[[], TrialWatch] = TrialWatch


def switch_environment(boot: Boot, args: Sequence[str]) -> TrialWatch | None:
    """Move to the environment that should run, if this is not it: then this does not
    return. `args` are `nestd`'s own. In a daemon running in an environment, the running
    watch.
    """
    try:
        return _switch(boot, args)
    except Exception:
        logger.exception("could not choose an environment; running on the base")
        return None


def _switch(boot: Boot, args: Sequence[str]) -> TrialWatch | None:
    files = StateFile(boot.root)
    running = running_environment(boot.root, boot.prefix)
    if running is not None:
        if files.load().current != running:
            return None
        watch = boot.watch()
        watch.start()
        return watch
    if boot.env.get(SWITCHED_ENV):
        logger.error("switched to %s but still run from %s", boot.env[SWITCHED_ENV], boot.prefix)
        return None
    before = files.load()
    state = _settled(
        boot.root,
        before.model_copy(
            update={"base_python": boot.executable, "base_fingerprint": boot.fingerprint()}
        ),
    )
    if state != before:
        files.save(state)
    if state.current is None:
        return None
    python = str(python_of(boot.root / state.current))
    logger.info("running from environment %s (boot %d)", state.current, state.boots)
    try:
        boot.exec_program(
            python, [python, "-m", "nestd", *args], {**boot.env, SWITCHED_ENV: state.current}
        )
    except OSError as error:
        logger.warning("could not start environment %s: %s", state.current, error)
        files.save(_went_back(boot.root, state))
    return None


def _settled(root: Path, state: UpdateState) -> UpdateState:
    """The state this base can run: an environment that used up its boots left, an unusable
    one gone from it (`environments.remove_unused` deletes the folder), and this boot
    counted.
    """
    fingerprint = state.base_fingerprint
    current = state.current
    if current is not None and (
        state.boots >= boot_limit(state) or (state.trial and not usable(root, current, fingerprint))
    ):
        logger.warning("environment %s did not come up; going back", current)
        state = _went_back(root, state)
    if state.ready is not None and not usable(root, state.ready, fingerprint):
        state = state.model_copy(update={"ready": None})
    previous = state.previous
    if previous not in (None, BASE) and not usable(root, previous, fingerprint):
        state = state.model_copy(update={"previous": None})
    current = state.current
    if current is not None and not usable(root, current, fingerprint):
        logger.warning("environment %s cannot run on this base; running on the base", current)
        current = None
    if current is None:
        return state.model_copy(
            update={"current": None, "previous": None, "boots": 0, "trial": False}
        )
    return state.model_copy(update={"boots": state.boots + 1})


def _went_back(root: Path, state: UpdateState) -> UpdateState:
    manifest = None if state.current is None else read_manifest(root / state.current)
    what = manifest.summary if manifest is not None else ""
    if state.trial:
        update = f"The update to {what}" if what else "The update"
        notice = f"{update} did not start, so Nest went back to the previous engines."
    else:
        engines = what or "the updated engines"
        notice = f"Nest could not start with {engines}, so it went back to the previous engines."
    return rolled_back(state, None if manifest is None else manifest.packages, notice)
