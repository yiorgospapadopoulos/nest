"""Files a chat's messages name, read for the in-app viewer (B144)."""

from collections.abc import Iterable
from pathlib import Path

from nestd.errors import NotFoundError


class NamedFileNotFoundError(NotFoundError):
    pass


def named_file(path: str, folder: Path | None, attachment_dirs: Iterable[Path]) -> Path:
    """The regular file `path` names, relative to the chat's folder or absolute, once it is
    resolved to inside that folder or one of the chat's attachment folders. Anything else,
    a link out of them included, is reported as not found, whatever it is.
    """
    roots = [root.resolve() for root in (folder, *attachment_dirs) if root is not None]
    base = folder if folder is not None else Path("/")
    missing = NamedFileNotFoundError("file not found")
    try:
        file = (base / path).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise missing from None
    if not file.is_file() or not any(file.is_relative_to(root) for root in roots):
        raise missing
    return file
