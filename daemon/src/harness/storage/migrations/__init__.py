"""Discovery of the numbered `NNNN_name.sql` migrations shipped in this package."""

import re
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable

from harness.storage.errors import DatabaseError

PACKAGED = files(__name__)
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def load_migrations(directory: Traversable = PACKAGED) -> list[Migration]:
    """Return migrations in order; versions must run 1, 2, 3... without gaps."""
    sql_files = sorted(
        (entry for entry in directory.iterdir() if entry.name.endswith(".sql")),
        key=lambda entry: entry.name,
    )
    migrations: list[Migration] = []
    for expected, entry in enumerate(sql_files, start=1):
        match = _NAME.match(entry.name)
        if match is None:
            msg = f"migration file {entry.name!r} does not match NNNN_name.sql"
            raise DatabaseError(msg)
        if int(match.group(1)) != expected:
            msg = f"expected migration {expected:04d}, found {entry.name!r}"
            raise DatabaseError(msg)
        migrations.append(Migration(expected, entry.name, entry.read_text(encoding="utf-8")))
    return migrations
