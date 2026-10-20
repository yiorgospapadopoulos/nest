"""Removing a worktree's trust entry from the user's Codex config (B91, D113).

Codex writes `[projects."<folder>"]` with `trust_level = "trusted"` into
`$CODEX_HOME/config.toml` for each folder a thread works in. When Nest removes one of its
worktrees, that table goes too. The file is edited as text, so everything else (comments,
order, formatting) stays byte for byte; it is written only when an entry was removed.
"""

import os
import re
import tempfile
import tomllib
from pathlib import Path

CONFIG_NAME = "config.toml"
# A table header line: `[projects."<path>"]`, maybe with a comment after it.
_PROJECT_HEADER = re.compile(r"^\s*\[\s*projects\s*\.\s*(?P<key>.+?)\s*\]\s*(?:#.*)?$")
_TABLE_HEADER = re.compile(r"^\s*\[")


def forget_trust(codex_home: Path, folder: Path) -> bool:
    """Remove `folder`'s project table; False when the file or the entry is not there."""
    config = codex_home / CONFIG_NAME
    try:
        original = config.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    names = {str(folder), str(folder.resolve())}
    kept: list[str] = []
    skipping = False
    removed = False
    for line in original.splitlines(keepends=True):
        header = _PROJECT_HEADER.match(line.rstrip("\r\n"))
        if header is not None:
            skipping = _key(header.group("key")) in names
            removed = removed or skipping
        elif _TABLE_HEADER.match(line):
            skipping = False
        if not skipping:
            kept.append(line)
    if not removed:
        return False
    _write(config, "".join(kept))
    return True


def _key(raw: str) -> str | None:
    """The project's path from its header's key, quoted as TOML quotes it."""
    try:
        parsed = tomllib.loads(f"[t.{raw}]\n")
    except tomllib.TOMLDecodeError:
        return None
    return next(iter(parsed["t"]))


def _write(path: Path, text: str) -> None:
    """Replace the file in one step, keeping its permissions."""
    mode = path.stat().st_mode
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=".config-", suffix=".toml")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(temporary).chmod(mode)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
