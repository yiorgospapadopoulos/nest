"""Untracked files as added files, read directly so the index is never touched."""

import asyncio
from dataclasses import dataclass
from pathlib import Path

from harness.review.models import DiffLine, FileDiff, Hunk

# Git's own test: a NUL byte near the start makes a file binary.
_BINARY_PROBE = 8000
# At most this much of a file is kept for showing (SH-08); the rest is only counted.
MAX_SHOWN_BYTES = 1_000_000
_CHUNK = 64 * 1024


async def untracked_diff(root: Path, path: str, max_lines: int) -> FileDiff:
    """An untracked file; git lists an untracked nested repository as its folder, `lib/`,
    which shows as a nested repository with no content (BUG-65).
    """
    nested = path.endswith("/")
    head = _Head(b"") if nested else await asyncio.to_thread(_read, root / path, max_lines)
    binary = b"\0" in head.content[:_BINARY_PROBE]
    lines = [] if binary else head.content.decode(errors="replace").splitlines()
    total = len(lines) if head.rest_lines is None or binary else head.rest_lines
    kept = [
        DiffLine(kind="add", text=text, old_line=None, new_line=number)
        for number, text in enumerate(lines[:max_lines], start=1)
    ]
    hunks = [Hunk(old_start=0, old_lines=0, new_start=1, new_lines=total, header="", lines=kept)]
    return FileDiff(
        path=path,
        old_path=None,
        status="added",
        additions=total,
        deletions=0,
        binary=binary,
        truncated=total > max_lines or (head.rest_lines is not None and not binary),
        hunks=hunks if lines else [],
        nested_repository=nested,
    )


@dataclass(frozen=True)
class _Head:
    # The start of the file, or all of it.
    content: bytes
    # The file's line count when `content` is only its start; None when it is all of it.
    rest_lines: int | None = None


def _read(file: Path, max_lines: int) -> _Head:
    """The file up to about `max_lines` lines or MAX_SHOWN_BYTES; past that, lines are
    counted the way git counts them (a last line without a newline counts too), not kept.
    """
    # Git records a symlink as its target path.
    if file.is_symlink():
        return _Head(str(file.readlink()).encode())
    kept = bytearray()
    newlines = 0
    complete = True
    last = b""
    with file.open("rb") as stream:
        while chunk := stream.read(_CHUNK):
            if complete and len(kept) < MAX_SHOWN_BYTES and newlines <= max_lines:
                kept += chunk
            else:
                complete = False
            newlines += chunk.count(b"\n")
            last = chunk[-1:]
    if complete:
        return _Head(bytes(kept))
    return _Head(bytes(kept[:MAX_SHOWN_BYTES]), newlines + (last != b"\n"))
