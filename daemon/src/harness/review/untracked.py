"""Untracked files as added files, read directly so the index is never touched."""

import asyncio
from pathlib import Path

from harness.review.models import DiffLine, FileDiff, Hunk

# Git's own test: a NUL byte near the start makes a file binary.
_BINARY_PROBE = 8000


async def untracked_diff(root: Path, path: str, max_lines: int) -> FileDiff:
    """An untracked file; git lists an untracked nested repository as its folder, `lib/`,
    which shows as added with no content.
    """
    content = b"" if path.endswith("/") else await asyncio.to_thread(_read, root / path)
    binary = b"\0" in content[:_BINARY_PROBE]
    lines = [] if binary else content.decode(errors="replace").splitlines()
    kept = [
        DiffLine(kind="add", text=text, old_line=None, new_line=number)
        for number, text in enumerate(lines[:max_lines], start=1)
    ]
    hunks = [
        Hunk(old_start=0, old_lines=0, new_start=1, new_lines=len(lines), header="", lines=kept)
    ]
    return FileDiff(
        path=path,
        old_path=None,
        status="added",
        additions=len(lines),
        deletions=0,
        binary=binary,
        truncated=len(lines) > max_lines,
        hunks=hunks if lines else [],
    )


def _read(file: Path) -> bytes:
    # Git records a symlink as its target path.
    return str(file.readlink()).encode() if file.is_symlink() else file.read_bytes()
