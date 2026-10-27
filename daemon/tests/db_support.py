"""A migrated database file made once per test process and copied for each test (B111)."""

import atexit
import shutil
import tempfile
from pathlib import Path

from nestd.storage.db import Database

# The template, once made.
_made: list[Path] = []


async def migrated_copy(path: Path) -> Path:
    """Put a copy of a fully migrated, empty database at `path`; opening it finds the
    schema current and runs no migration. Migration tests open fresh paths instead.
    """
    if not _made:
        folder = Path(tempfile.mkdtemp(prefix="nest-db-template-"))
        atexit.register(shutil.rmtree, folder, ignore_errors=True)
        # Closing the only connection folds the write-ahead log into the file.
        database = await Database.open(folder / "nest.db")
        await database.close()
        _made.append(folder / "nest.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_made[0], path)
    return path
