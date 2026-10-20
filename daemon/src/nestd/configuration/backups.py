"""A backup before every change Nest makes to the engines' files (contract rule 2).

Each change gets `<data_dir>/config-backups/<UTC time>-<op>/`, holding a copy of every
file, folder or link it touches at its absolute path (links copied as links), and a
manifest. The newest `KEEP` backups stay. A copy to Shared can be undone from its backup:
the paths it marked restorable are put back if nothing changed them since.
"""

import re
import shutil
from pathlib import Path

from pydantic import BaseModel, Field

from nestd.clock import Clock
from nestd.configuration.errors import ChangedOnDiskError, UnknownItemError
from nestd.configuration.files import tree_version

KEEP = 50
MANIFEST = "nest-backup.json"
_ID = re.compile(r"^\d{8}T\d{12}Z-[a-z0-9-]+$")


class _Entry(BaseModel):
    path: str
    # Whether there was something at the path to copy.
    saved: bool
    # Put back by an undo; `.claude.json` and Codex's config.toml are backed up only, as
    # their engines write other parts of them all the time.
    restore: bool
    # Its fingerprint after the change, for an undo to see whether it changed since.
    after: str | None = None


class _Manifest(BaseModel):
    op: str
    entries: list[_Entry] = Field(default_factory=list[_Entry])
    undoable: bool = False
    undone: bool = False
    # MCP servers the change added, by engine, for an undo to remove.
    added_servers: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])


class Backup:
    def __init__(self, folder: Path, manifest: _Manifest) -> None:
        self.folder = folder
        self._manifest = manifest

    @classmethod
    def create(cls, folder: Path, op: str) -> "Backup":
        backup = cls(folder, _Manifest(op=op))
        backup._write()
        return backup

    @property
    def id(self) -> str:
        return self.folder.name

    @property
    def added_servers(self) -> dict[str, list[str]]:
        return self._manifest.added_servers

    def save(self, path: Path, *, restore: bool = True) -> None:
        """Copy what is at `path` now, once per backup."""
        if any(entry.path == str(path) for entry in self._manifest.entries):
            return
        saved = _copy(path, self._mirror(path))
        self._manifest.entries.append(_Entry(path=str(path), saved=saved, restore=restore))
        self._write()

    def finish_undoable(self, added_servers: dict[str, list[str]]) -> None:
        """The change is done: remember how its paths look now, for an undo."""
        for entry in self._manifest.entries:
            entry.after = tree_version(Path(entry.path))
        self._manifest.undoable = True
        self._manifest.added_servers = added_servers
        self._write()

    def restore(self) -> None:
        """Put back every restorable path; 409 naming the first one changed since, or
        when this backup was undone already, and nothing is touched.
        """
        if not self._manifest.undoable:
            msg = f"backup {self.id} cannot be undone"
            raise UnknownItemError(msg)
        if self._manifest.undone:
            msg = "this copy was undone already"
            raise ChangedOnDiskError(msg, None)
        entries = [entry for entry in self._manifest.entries if entry.restore]
        for entry in entries:
            current = tree_version(Path(entry.path))
            if current != entry.after:
                msg = f"{entry.path} changed since the copy"
                raise ChangedOnDiskError(msg, current)
        for entry in entries:
            path = Path(entry.path)
            remove(path)
            if entry.saved:
                _copy(self._mirror(path), path)
        self._manifest.undone = True
        self._write()

    def _mirror(self, path: Path) -> Path:
        return self.folder / path.relative_to(path.anchor)

    def _write(self) -> None:
        (self.folder / MANIFEST).write_text(self._manifest.model_dump_json(), encoding="utf-8")


class Backups:
    def __init__(self, root: Path, clock: Clock, keep: int = KEEP) -> None:
        self._root = root
        self._clock = clock
        self._keep = keep

    def start(self, op: str) -> Backup:
        """A new, empty backup for the change `op`; the oldest beyond `keep` go."""
        base = f"{self._clock.now():%Y%m%dT%H%M%S%fZ}-{op}"
        folder = self._root / base
        count = 1
        while folder.exists():
            count += 1
            folder = self._root / f"{base}-{count}"
        folder.mkdir(parents=True)
        backup = Backup.create(folder, op)
        self._prune()
        return backup

    def load(self, backup_id: str) -> Backup:
        """404 when there is no such backup."""
        folder = self._root / backup_id
        manifest = folder / MANIFEST
        if not _ID.match(backup_id) or not manifest.is_file():
            msg = f"no backup {backup_id!r}"
            raise UnknownItemError(msg)
        return Backup(folder, _Manifest.model_validate_json(manifest.read_text(encoding="utf-8")))

    def _prune(self) -> None:
        folders = sorted(entry for entry in self._root.iterdir() if entry.is_dir())
        for folder in folders[: max(0, len(folders) - self._keep)]:
            shutil.rmtree(folder)


def remove(path: Path) -> None:
    """Remove a file, link or folder (a link's target stays); nothing when missing."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _copy(source: Path, destination: Path) -> bool:
    """Copy a file, link (as a link) or folder; False when there is nothing at `source`."""
    if not source.is_symlink() and not source.exists():
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_symlink():
        destination.symlink_to(source.readlink())
    elif source.is_dir():
        shutil.copytree(source, destination, symlinks=True)
    else:
        shutil.copy2(source, destination)
    return True
