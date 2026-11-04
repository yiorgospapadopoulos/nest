"""The prepared environments in `<data_dir>/environments/<id>/`, full venvs.

The base (the checkout's `.venv`, where the service files start) is never changed. Only
folders named like one Nest makes are ever removed.
"""

import logging
import re
import secrets
import shutil
from collections.abc import Collection, Iterable
from pathlib import Path

from nestd.updates.manifest import Manifest, read_manifest
from nestd.updates.state import BASE, UpdateState

logger = logging.getLogger(__name__)

PARTIAL_SUFFIX = ".partial"
_ID_BYTES = 6
_NAME = re.compile(rf"[0-9a-f]{{{_ID_BYTES * 2}}}(?:{re.escape(PARTIAL_SUFFIX)})?")


def new_environment_id() -> str:
    return secrets.token_hex(_ID_BYTES)


def python_of(environment: Path) -> Path:
    return environment / "bin" / "python"


def running_environment(root: Path, prefix: Path) -> str | None:
    """The environment `prefix` (this process's `sys.prefix`) is, None for any other place."""
    resolved = prefix.resolve()
    return resolved.name if resolved.parent == root.resolve() else None


def usable(root: Path, environment: str, fingerprint: str | None) -> Manifest | None:
    """Its manifest when it can run on this base; None when it is broken or was made from
    another base.
    """
    folder = root / environment
    manifest = read_manifest(folder)
    if manifest is None or manifest.base_fingerprint != fingerprint:
        return None
    return manifest if python_of(folder).is_file() else None


def kept_folders(state: UpdateState) -> frozenset[str]:
    names = (state.current, state.previous, state.ready)
    return frozenset(name for name in names if name is not None and name != BASE)


def remove_unused(root: Path, keep: Collection[str]) -> list[str]:
    """Every environment folder not in `keep`, half-made ones included; what went."""
    removed: list[str] = []
    for entry in _folders(root):
        if entry.name not in keep and _NAME.fullmatch(entry.name):
            shutil.rmtree(entry, ignore_errors=True)
            removed.append(entry.name)
    return removed


def kept_versions(root: Path, engine_id: str) -> frozenset[str]:
    """The versions of an ACP engine the environments on disk hold, for whoever clears out
    old versions: an environment's engine must still be there when it runs.
    """
    versions: set[str] = set()
    for entry in _folders(root):
        manifest = read_manifest(entry)
        if manifest is not None and engine_id in manifest.packages:
            versions.add(manifest.packages[engine_id])
    return frozenset(versions)


def _folders(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return ()
    return [entry for entry in root.iterdir() if entry.is_dir() and not entry.is_symlink()]
