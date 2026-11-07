"""Which environment the daemon runs from, in `<data_dir>/environments/state.json`.

Written whole to a temporary file and renamed, so a reader sees the old state or the new
one. The steps are plain functions; the boot switch and the service save what they return.
"""

import logging
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

STATE_NAME = "state.json"
# `previous` when the environment to go back to is the base one.
BASE = "base"
# Boots of an environment that once worked, with no confirm between them, before it is left.
BOOT_LIMIT = 3


class UpdateState(BaseModel):
    # The environment to run; None is the base.
    current: str | None = None
    # What Undo returns to: an environment, BASE, or None when there is nothing.
    previous: str | None = None
    # The environment prepared and checked, waiting for Relaunch.
    ready: str | None = None
    # Boots handed to `current` since one last confirmed (`boot.py`).
    boots: int = 0
    # `current` has not confirmed even once since the relaunch: one failed boot is enough.
    trial: bool = False
    notice: str | None = None
    # The package versions (engine id to version) of updates that failed and were rolled
    # back, exactly as they were: not offered again until one that differs has been prepared.
    refused: list[Mapping[str, str]] = []
    # The base as it last started: only it can tell, and it always runs first.
    base_python: str | None = None
    base_fingerprint: str | None = None


def write_atomically(path: Path, text: str) -> None:
    """A reader sees the old file or the new one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


class StateFile:
    def __init__(self, root: Path) -> None:
        self.path = root / STATE_NAME

    def load(self) -> UpdateState:
        """An unreadable state counts as none: the daemon then runs on the base."""
        try:
            return UpdateState.model_validate_json(self.path.read_bytes())
        except FileNotFoundError:
            return UpdateState()
        except (OSError, ValidationError) as error:
            logger.warning("could not read %s (%s)", self.path, type(error).__name__)
            return UpdateState()

    def save(self, state: UpdateState) -> None:
        write_atomically(self.path, state.model_dump_json())


def relaunched(state: UpdateState) -> UpdateState:
    """Swap to the ready environment; only the one it replaces is kept to go back to."""
    return state.model_copy(
        update={
            "previous": state.current or BASE,
            "current": state.ready,
            "ready": None,
            "boots": 0,
            "trial": True,
        }
    )


def boot_limit(state: UpdateState) -> int:
    return 1 if state.trial else BOOT_LIMIT


def confirmed(state: UpdateState) -> UpdateState:
    return state.model_copy(update={"boots": 0, "trial": False})


def undone(state: UpdateState) -> UpdateState:
    """Back to the previous environment. The one left is offered again as it stands, unless
    another is already ready: that one stays and cleanup takes the one left.
    """
    return _back(state).model_copy(update={"ready": state.ready or state.current})


def rolled_back(state: UpdateState, failed: Mapping[str, str] | None, notice: str) -> UpdateState:
    """Back to the previous environment; `failed` is what would not run."""
    refused = state.refused if failed is None else [*state.refused, failed]
    return _back(state).model_copy(update={"refused": refused, "notice": notice})


def _back(state: UpdateState) -> UpdateState:
    return state.model_copy(
        update={
            "current": None if state.previous == BASE else state.previous,
            "previous": None,
            "boots": 0,
            "trial": False,
        }
    )
