"""Where Claude Code keeps a folder's chats: `<claude dir>/projects/<encoded folder>`."""

import os
import re
import unicodedata
from pathlib import Path

# Claude Code cuts longer names and adds a hash, which differs between its runtimes, so
# folders are matched by this prefix and then by the cwd recorded in each chat.
MAX_ENCODED_LENGTH = 200
_NOT_ALPHANUMERIC = re.compile(r"[^a-zA-Z0-9]")


def encode_folder(path: Path) -> str:
    """Every character but ASCII letters and digits becomes `-`, as in Claude Code."""
    return _NOT_ALPHANUMERIC.sub("-", unicodedata.normalize("NFC", str(path)))


def candidate_dirs(projects_dir: Path, folder: Path) -> list[Path]:
    """Project dirs that may hold chats of `folder` or of folders inside it.

    The prefix also matches siblings such as `<folder>-old`; callers check each chat's cwd.
    A folder reached through a link also finds the dirs named after the link's target.
    """
    prefixes = tuple(
        encode_folder(path)[:MAX_ENCODED_LENGTH]
        for path in (folder, Path(os.path.realpath(folder)))
    )
    try:
        entries = sorted(projects_dir.iterdir())
    except OSError:
        return []
    return [entry for entry in entries if entry.name.startswith(prefixes) and entry.is_dir()]
