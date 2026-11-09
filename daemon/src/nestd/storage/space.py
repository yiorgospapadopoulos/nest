"""How much disk space Nest's data folder uses, by kind (D104, D165)."""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from nestd.paths import AppPaths

type Part = Literal["chats", "attachments", "artifacts", "engines", "backups", "logs", "other"]

# Backups made by Nest's config changes, and by deploys under `backups-<block>/`.
CONFIG_BACKUPS_DIR = "config-backups"
DEPLOY_BACKUPS_PREFIX = "backups"
# The folder a move from the old name leaves behind (folder_move.py).
MOVE_BACKUP_SUFFIX = ".harness-backup"


class StorageUsage(BaseModel):
    total_bytes: int
    # The SQLite database with its WAL and SHM files.
    chats_bytes: int
    attachments_bytes: int
    artifacts_bytes: int
    # The engine environments the daemon runs in (B121), the extra engines it installed and
    # voice input's engine and model (B154).
    engines_bytes: int
    # Copies of the database and of changed config files.
    backups_bytes: int
    logs_bytes: int
    # Everything else in the data folder.
    other_bytes: int


def measure(paths: AppPaths) -> StorageUsage:
    """Sizes of the files under the data folder; links are counted, never followed."""
    sizes: dict[Part, int] = dict.fromkeys(
        ("chats", "attachments", "artifacts", "engines", "backups", "logs", "other"), 0
    )
    try:
        entries = list(os.scandir(paths.data_dir))
    except OSError:
        entries = []
    for entry in entries:
        path = Path(entry.path)
        size = _tree_size(path) if entry.is_dir(follow_symlinks=False) else _size(path)
        sizes[_part(paths, entry.name)] += size
    return StorageUsage(
        total_bytes=sum(sizes.values()),
        chats_bytes=sizes["chats"],
        attachments_bytes=sizes["attachments"],
        artifacts_bytes=sizes["artifacts"],
        engines_bytes=sizes["engines"],
        backups_bytes=sizes["backups"],
        logs_bytes=sizes["logs"],
        other_bytes=sizes["other"],
    )


def _part(paths: AppPaths, name: str) -> Part:
    """The part a top-level item of the data folder belongs to, by its name."""
    database = paths.db_path.name
    folders: dict[str, Part] = {
        paths.attachments_dir.name: "attachments",
        paths.artifacts_dir.name: "artifacts",
        paths.environments_dir.name: "engines",
        paths.engines_dir.name: "engines",
        paths.voice_dir.name: "engines",
        paths.logs_dir.name: "logs",
        CONFIG_BACKUPS_DIR: "backups",
    }
    if name in (database, f"{database}-wal", f"{database}-shm"):
        return "chats"
    if name in folders:
        return folders[name]
    # `nest.db.before-b88-...` and its own -wal and -shm are copies of the database.
    if name.startswith((f"{database}.", DEPLOY_BACKUPS_PREFIX)) or name.endswith(
        MOVE_BACKUP_SUFFIX
    ):
        return "backups"
    return "other"


def _size(file: Path) -> int:
    try:
        return file.lstat().st_size
    except OSError:
        return 0


def _tree_size(root: Path) -> int:
    total = 0
    pending = [root]
    while pending:
        try:
            entries = list(os.scandir(pending.pop()))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                pending.append(Path(entry.path))
            else:
                total += _size(Path(entry.path))
    return total
