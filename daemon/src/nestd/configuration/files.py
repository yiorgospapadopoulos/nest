"""Reading and writing the engines' files: versions, atomic writes, folder fingerprints."""

import hashlib
import os
import tempfile
from pathlib import Path


def version_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_version(path: Path) -> str | None:
    """The sha256 of the file's bytes; None when there is no file."""
    try:
        return version_of(path.read_bytes())
    except FileNotFoundError:
        return None


def read_text(path: Path) -> str:
    """The file's text; "" when there is none."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def write_text(path: Path, text: str) -> str:
    """Replace the file in one step, keeping its permissions; folders are created as
    needed. Returns the new version.
    """
    data = text.encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode if path.exists() else None
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as file:
            file.write(data)
        if mode is not None:
            Path(temporary).chmod(mode)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return version_of(data)


def tree_version(path: Path) -> str | None:
    """A fingerprint of a file, link or folder (links not followed); None when missing."""
    lines: list[str] = []
    _describe(path, Path(), lines)
    return version_of("\n".join(lines).encode()) if lines else None


def _describe(path: Path, relative: Path, lines: list[str]) -> None:
    if path.is_symlink():
        lines.append(f"link {relative} {path.readlink()}")
    elif path.is_dir():
        lines.append(f"dir {relative}")
        for entry in sorted(path.iterdir()):
            _describe(entry, relative / entry.name, lines)
    elif path.is_file():
        lines.append(f"file {relative} {version_of(path.read_bytes())}")
