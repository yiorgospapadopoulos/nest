"""Moves the config and data folders from their names before the rename to Nest (B43).

On start, when a default folder of Nest is missing and harness's is there, the old folder
is copied (links kept as links, permissions kept, the SQLite database with its -wal and
-shm), the copy takes the new name, the old folder is renamed `<old>.harness-backup`, and
a link at the old path leads to the new folder. Absolute paths stored before the move
(worktrees, attachments, pixie folders, git's worktree records) keep working through it.

Nothing is ever deleted. The copy is made under a temporary name and only takes the new
name once complete, so a failure leaves the old folder untouched and the daemon never
opens half a copy. A marker in the new folder lets a later start finish a move that
stopped after the copy. Once done, a start does nothing.
"""

import os
import shutil
import socket
import stat
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from nestd.auth.token_socket import SOCKET_NAME
from nestd.paths import (
    CONFIG_DIR_ENV,
    DATA_DIR_ENV,
    DB_NAME,
    default_config_dir,
    default_data_dir,
    env_value,
)
from nestd.service.launchd import LEGACY_LABEL

LEGACY_NAME = "harness"
LEGACY_DB_NAME = "harness.db"
BACKUP_SUFFIX = ".harness-backup"
# The copy's name until it is complete.
STAGING_SUFFIX = ".moving"
# Written into the copy: the folder it was moved from.
MARKER_NAME = ".moved-from-harness"
# SQLite's files next to a database, renamed with it (the main file last).
DB_SIDECARS = ("-wal", "-shm", "-journal")

type Serving = Callable[[Path], bool]


class FolderMoveError(Exception):
    """A folder could not be moved; the message says what is left where."""


@dataclass(frozen=True)
class FolderMove:
    old: Path
    new: Path


def answers(path: Path) -> bool:
    """Whether a daemon is listening on the Unix socket at `path`."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        try:
            sock.connect(str(path))
        except OSError:
            return False
    return True


def legacy_moves(env: Mapping[str, str], home: Path) -> list[FolderMove]:
    """The default folders to move; a folder named by a variable (new or old name) stays."""
    moves: list[FolderMove] = []
    if env_value(env, CONFIG_DIR_ENV) is None:
        moves.append(FolderMove(default_config_dir(home, LEGACY_NAME), default_config_dir(home)))
    if env_value(env, DATA_DIR_ENV) is None:
        moves.append(FolderMove(default_data_dir(home, LEGACY_NAME), default_data_dir(home)))
    return moves


def move_folder(move: FolderMove, serving: Serving = answers) -> str | None:
    """Move the folder if it needs it; what was done, or None when nothing was."""
    old, new = move.old, move.new
    if os.path.lexists(new):
        return _finish(move)
    if not old.is_dir():
        return None
    staging = new.with_name(new.name + STAGING_SUFFIX)
    if os.path.lexists(staging):
        msg = (
            f"{staging} is left from a move that did not finish; {old} is untouched. "
            "Remove it and start again."
        )
        raise FolderMoveError(msg)
    if os.path.lexists(_backup(old)):
        msg = f"{_backup(old)} already exists; move it away and start again ({old} is untouched)"
        raise FolderMoveError(msg)
    _check_not_serving(old, serving)
    try:
        staging.mkdir(mode=0o700, parents=True)
        shutil.copytree(old, staging, symlinks=True, ignore=_special_files, dirs_exist_ok=True)
        _rename_database(staging)
        (staging / MARKER_NAME).write_text(f"{old}\n", encoding="utf-8")
        staging.rename(new)
    except OSError as error:
        msg = f"could not copy {old} to {new}: {error}; {old} is untouched"
        raise FolderMoveError(msg) from error
    return _finish(move)


def adopt_legacy_database(data_dir: Path, serving: Serving = answers) -> bool:
    """Give a database from before the rename its new name, in a data folder named by a
    variable or just moved; whether it did. An existing new database is never replaced."""
    if os.path.lexists(data_dir / DB_NAME) or not (data_dir / LEGACY_DB_NAME).is_file():
        return False
    _check_not_serving(data_dir, serving)
    _rename_database(data_dir)
    return True


def _finish(move: FolderMove) -> str | None:
    """Rename the old folder to its backup and link the old path to the new folder, for a
    copy that is complete (it has the marker). Nothing to do once the link is there, or
    when the user removed both the link and the backup."""
    old, new, backup = move.old, move.new, _backup(move.old)
    if not (new / MARKER_NAME).is_file() or old.is_symlink():
        return None
    try:
        if old.is_dir():
            if os.path.lexists(backup):
                msg = f"{backup} already exists"
                raise FileExistsError(msg)
            old.rename(backup)
        if os.path.lexists(old) or not os.path.lexists(backup):
            return None
        old.symlink_to(new, target_is_directory=True)
    except OSError as error:
        msg = f"could not finish moving {old} to {new}: {error}; {new} holds the copy"
        raise FolderMoveError(msg) from error
    return (
        f"Moved {old} to {new}; the old folder is kept as {backup}, "
        "with a link to the new one at its place"
    )


def _backup(old: Path) -> Path:
    return old.with_name(old.name + BACKUP_SUFFIX)


def _check_not_serving(folder: Path, serving: Serving) -> None:
    if serving(folder / SOCKET_NAME):
        msg = (
            f"the daemon from before the rename is still running on {folder}; stop it "
            f"first (launchctl bootout gui/{os.getuid()}/{LEGACY_LABEL})"
        )
        raise FolderMoveError(msg)


def _special_files(directory: str, names: list[str]) -> set[str]:
    """Sockets and pipes, which cannot be copied; the daemon makes its socket again."""
    return {
        name
        for name in names
        if stat.S_ISSOCK(mode := (Path(directory) / name).lstat().st_mode) or stat.S_ISFIFO(mode)
    }


def _rename_database(folder: Path) -> None:
    """`harness.db` and its sidecars to `nest.db`; the sidecars first, so a stop part way
    never leaves the new database without its -wal."""
    if not (folder / LEGACY_DB_NAME).is_file():
        return
    for suffix in DB_SIDECARS:
        sidecar = folder / (LEGACY_DB_NAME + suffix)
        if os.path.lexists(sidecar):
            sidecar.rename(folder / (DB_NAME + suffix))
    (folder / LEGACY_DB_NAME).rename(folder / DB_NAME)
