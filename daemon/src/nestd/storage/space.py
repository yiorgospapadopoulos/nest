"""How much disk space Nest's data folder uses, by kind (D104)."""

import os
from pathlib import Path

from pydantic import BaseModel

from nestd.paths import AppPaths

# Where B79's artifacts live; counted as 0 until it exists.
ARTIFACTS_DIR = "artifacts"


class StorageUsage(BaseModel):
    total_bytes: int
    # The SQLite database with its WAL and SHM files.
    chats_bytes: int
    attachments_bytes: int
    artifacts_bytes: int
    # Everything else in the data folder, such as worktrees and logs.
    other_bytes: int


def measure(paths: AppPaths) -> StorageUsage:
    """Sizes of the files under the data folder; links are counted, never followed."""
    database = {
        paths.db_path.with_name(paths.db_path.name + suffix) for suffix in ("", "-wal", "-shm")
    }
    attachments = paths.attachments_dir
    artifacts = paths.data_dir / ARTIFACTS_DIR
    chats = sum(_size(file) for file in database)
    attachments_bytes = _tree_size(attachments)
    artifacts_bytes = _tree_size(artifacts)
    everything = _tree_size(paths.data_dir)
    other = max(everything - chats - attachments_bytes - artifacts_bytes, 0)
    return StorageUsage(
        total_bytes=chats + attachments_bytes + artifacts_bytes + other,
        chats_bytes=chats,
        attachments_bytes=attachments_bytes,
        artifacts_bytes=artifacts_bytes,
        other_bytes=other,
    )


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
