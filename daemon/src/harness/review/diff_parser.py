"""Parse `git diff` output: `--raw -z` for paths and modes, the patch for hunks."""

import re
from dataclasses import dataclass, field
from typing import NamedTuple

from harness.review.models import DiffLine, FileStatus, Hunk, LineKind

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@ ?(.*)$")
_STATUSES: dict[str, FileStatus] = {"A": "added", "D": "deleted", "R": "renamed", "C": "added"}
_HEADER = "diff --git "
# Extended header lines naming the new path of a renamed or copied file.
_NEW_PATH = ("rename to ", "copy to ")
# Git's escapes in quoted paths, besides octal bytes.
_ESCAPES = {"a": 7, "b": 8, "t": 9, "n": 10, "v": 11, "f": 12, "r": 13, '"': 34, "\\": 92}


@dataclass
class PatchFile:
    """One file's part of a patch."""

    # The file's path (its new path, for a rename or copy).
    path: str = ""
    hunks: list[Hunk] = field(default_factory=list[Hunk])
    additions: int = 0
    deletions: int = 0
    binary: bool = False
    truncated: bool = False

    def add(self, other: "PatchFile") -> None:
        """Take in another section of the same file, as a typechange has two."""
        self.hunks += other.hunks
        self.additions += other.additions
        self.deletions += other.deletions
        self.binary = self.binary or other.binary
        self.truncated = self.truncated or other.truncated


class RawEntry(NamedTuple):
    status: FileStatus
    # The old path of a rename or copy.
    old_path: str | None
    path: str
    # Git's octal modes, such as `100644`, `160000` for a gitlink, `000000` for none.
    old_mode: str
    new_mode: str


def parse_raw(output: str) -> list[RawEntry]:
    """Each file of `git diff --raw -z` output, in git's order."""
    tokens = iter(output.split("\0"))
    entries: list[RawEntry] = []
    for meta in tokens:
        if not meta:
            continue
        old_mode, new_mode, _, _, code = meta.removeprefix(":").split(" ")
        old_path = next(tokens) if code[0] in "RC" else None
        status = _STATUSES.get(code[0], "modified")
        entries.append(RawEntry(status, old_path, next(tokens), old_mode, new_mode))
    return entries


def parse_patch(patch: str, max_lines: int) -> list[PatchFile]:
    """Each file's hunks, in git's order; at most `max_lines` lines are kept per file."""
    files: list[PatchFile] = []
    current = PatchFile()
    hunk: Hunk | None = None
    old = new = kept = 0
    for line in patch.split("\n"):
        if line.startswith(_HEADER):
            current, hunk, kept = PatchFile(_header_path(line[len(_HEADER) :])), None, 0
            files.append(current)
        elif hunk is None and line.startswith(_NEW_PATH):
            current.path = _path(line.split(" ", 2)[2])
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


def by_path(files: list[PatchFile]) -> dict[str, PatchFile]:
    """Each file's part of a patch by its path, with the sections of one file combined."""
    found: dict[str, PatchFile] = {}
    for part in files:
        if part.path in found:
            found[part.path].add(part)
        else:
            found[part.path] = part
    return found


def _header_path(names: str) -> str:
    """The path in `a/<path> b/<path>`. A rename's names differ, but its `rename to` line
    follows and names it.
    """
    if names.startswith('"'):
        return _unquote(names)[0].removeprefix("a/")
    # Unquoted, both names are the same path, which may itself hold " b/".
    return names[2 : (len(names) - 1) // 2]


def _path(name: str) -> str:
    return _unquote(name)[0] if name.startswith('"') else name


def _unquote(text: str) -> tuple[str, str]:
    """The name git quoted at the start of `text`, and what follows it."""
    raw = bytearray()
    index = 1
    while text[index] != '"':
        char = text[index]
        if char != "\\":
            raw += char.encode()
            index += 1
        elif text[index + 1] in _ESCAPES:
            raw.append(_ESCAPES[text[index + 1]])
            index += 2
        else:
            raw.append(int(text[index + 1 : index + 4], 8))
            index += 4
    return raw.decode(errors="replace"), text[index + 1 :]
