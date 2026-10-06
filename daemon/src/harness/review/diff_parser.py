"""Parse `git diff` output: `--name-status -z` for paths, the patch for hunks."""

import re
from dataclasses import dataclass, field

from harness.review.models import DiffLine, FileStatus, Hunk, LineKind

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_STATUSES: dict[str, FileStatus] = {"A": "added", "D": "deleted", "R": "renamed", "C": "added"}


@dataclass
class PatchFile:
    """One file's part of a patch."""

    hunks: list[Hunk] = field(default_factory=list[Hunk])
    additions: int = 0
    deletions: int = 0
    binary: bool = False
    truncated: bool = False


def parse_name_status(output: str) -> list[tuple[FileStatus, str | None, str]]:
    """(status, old path for renames and copies, path) in git's order."""
    tokens = iter(output.split("\0"))
    entries: list[tuple[FileStatus, str | None, str]] = []
    for code in tokens:
        if not code:
            continue
        status = _STATUSES.get(code[0], "modified")
        if code[0] in "RC":
            old = next(tokens)
            entries.append((status, old, next(tokens)))
        else:
            entries.append((status, None, next(tokens)))
    return entries


def parse_patch(patch: str, max_lines: int) -> list[PatchFile]:
    """Each file's hunks, in git's order; at most `max_lines` lines are kept per file."""
    files: list[PatchFile] = []
    current = PatchFile()
    hunk: Hunk | None = None
    old = new = kept = 0
    for line in patch.split("\n"):
        if line.startswith("diff --git "):
            current, hunk, kept = PatchFile(), None, 0
            files.append(current)
        elif match := _HUNK.match(line):
            old, new = int(match.group(1)), int(match.group(3))
            hunk = Hunk(
                old_start=old,
                old_lines=int(match.group(2) or 1),
                new_start=new,
                new_lines=int(match.group(4) or 1),
                header=match.group(5),
                lines=[],
            )
            if not current.truncated:
                current.hunks.append(hunk)
        elif hunk is None:
            current.binary = current.binary or line.startswith(("Binary files ", "GIT binary"))
        elif line[:1] in (" ", "+", "-"):
            kind, old_line, new_line = _line(line[0], old, new)
            old += old_line is not None
            new += new_line is not None
            current.additions += kind == "add"
            current.deletions += kind == "delete"
            if kept >= max_lines:
                current.truncated = True
                continue
            hunk.lines.append(
                DiffLine(kind=kind, text=line[1:], old_line=old_line, new_line=new_line)
            )
            kept += 1
    return files


def _line(prefix: str, old: int, new: int) -> tuple[LineKind, int | None, int | None]:
    if prefix == "+":
        return "add", None, new
    if prefix == "-":
        return "delete", old, None
    return "context", old, new
