"""The files of a multi-file HTML page (B88 stage 3, D117). An agent sends them with the page;
the page builder inlines the ones the page names and hands all of them to the page, where
`window.nest.files` reads them. A version is complete in itself: its files are its own.
"""

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError

from nestd.artifacts.models import InvalidArtifactError, PageFile
from nestd.pixies.habit_models import problems

FILES_MAX = 100
PATH_MAX = 200
# Bytes of a version in all: its content plus its files.
VERSION_MAX = 16 * 1024 * 1024

_SEGMENT = r"[A-Za-z0-9._-]*[A-Za-z0-9_-][A-Za-z0-9._-]*|[A-Za-z0-9_-]"
_PATH = re.compile(rf"(?!.*(?:^|/)\.\.?(?:/|$))(?:{_SEGMENT})(?:/(?:{_SEGMENT}))*")

MIME_TYPES: dict[str, str] = {
    "js": "text/javascript",
    "css": "text/css",
    "json": "application/json",
    "csv": "text/csv",
    "txt": "text/plain",
    "md": "text/markdown",
    "svg": "image/svg+xml",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "html": "text/html",
}
OTHER_MIME = "application/octet-stream"


@dataclass(frozen=True)
class FileData:
    path: str
    data: bytes
    mime: str

    @property
    def listed(self) -> PageFile:
        return PageFile(path=self.path, size=len(self.data), mime=self.mime)


class _FileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str
    encoding: Literal["utf8", "base64"] = "utf8"


def mime_of(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return MIME_TYPES.get(extension, OTHER_MIME)


def checked_files(files: list[dict[str, JsonValue]], content_size: int) -> list[FileData]:
    """The files decoded, in order; refused with the reason an agent can act on."""
    if len(files) > FILES_MAX:
        msg = f"a page has at most {FILES_MAX} files; this one has {len(files)}"
        raise InvalidArtifactError(msg)
    checked: list[FileData] = []
    seen: set[str] = set()
    total = content_size
    for index, entry in enumerate(files):
        where = f"files[{index}]"
        try:
            file = _FileIn.model_validate(entry)
        except ValidationError as error:
            raise InvalidArtifactError(f"{where}.{problems(error)}") from error
        if len(file.path) > PATH_MAX or not _PATH.fullmatch(file.path):
            msg = (
                f"{where}.path {file.path!r} must be a relative path of at most {PATH_MAX}"
                " characters: segments of letters, digits, dot, dash and underscore joined by /,"
                " with no . or .. segment and no leading /"
            )
            raise InvalidArtifactError(msg)
        if file.path.lower() in seen:
            msg = f"{where}.path {file.path!r} is used twice (paths are compared ignoring case)"
            raise InvalidArtifactError(msg)
        seen.add(file.path.lower())
        data = _decoded(file, where)
        total += len(data)
        checked.append(FileData(file.path, data, mime_of(file.path)))
    if total > VERSION_MAX:
        msg = (
            f"the page and its files are {total} bytes; a version holds at most {VERSION_MAX}"
            " bytes (16 MiB) in all"
        )
        raise InvalidArtifactError(msg)
    return checked


def _decoded(file: _FileIn, where: str) -> bytes:
    if file.encoding == "base64":
        try:
            return base64.b64decode(file.content, validate=True)
        except (binascii.Error, ValueError) as error:
            msg = f"{where}.content is not valid base64"
            raise InvalidArtifactError(msg) from error
    try:
        return file.content.encode()
    except UnicodeEncodeError as error:
        msg = f"{where}.content is not valid text (it has a lone surrogate)"
        raise InvalidArtifactError(msg) from error
