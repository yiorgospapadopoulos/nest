"""What an artifact is on the wire (B79), and the limits of what an agent may save."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from nestd.errors import ConflictError, InvalidInputError, NotFoundError

type ArtifactKind = Literal["markdown", "html"]
KINDS: tuple[ArtifactKind, ...] = ("markdown", "html")
EXTENSIONS: dict[ArtifactKind, str] = {"markdown": "md", "html": "html"}
TITLE_MAX = 200
# Bytes of a version's UTF-8 content.
CONTENT_MAX = 1024 * 1024
# Artifacts a listing returns at most, the most recently updated first.
LIST_MAX = 500

type SaveAction = Literal["created", "updated"]


class ArtifactNotFoundError(NotFoundError):
    pass


class InvalidArtifactError(InvalidInputError):
    pass


class ForeignArtifactError(ConflictError):
    """An agent tried to update an artifact of another chat or pixie."""


class Artifact(BaseModel):
    id: str
    # The title of its latest version.
    title: str
    kind: ArtifactKind
    # The project of the chat that saved it; `pixie:<id>` for a pixie's chat or habit run.
    repo: str
    session_id: str | None
    # The chat's title now, or the last one it had once deleted.
    chat_title: str | None
    chat_deleted: bool
    pixie_id: str | None
    pixie_name: str | None
    created_at: datetime
    # When its latest version was saved.
    updated_at: datetime
    latest_version: int
    version_count: int
    # The user opened its latest version.
    seen: bool


class ArtifactVersion(BaseModel):
    version: int
    title: str
    size: int
    created_at: datetime


class ArtifactDetail(Artifact):
    # Oldest first.
    versions: list[ArtifactVersion]


class VersionContent(BaseModel):
    artifact_id: str
    version: int
    kind: ArtifactKind
    title: str
    # As saved.
    content: str
    # The whole document a client shows in its sandbox (B82): the content of an HTML
    # artifact, a rendering page around a Markdown one.
    page: str
    size: int
    created_at: datetime


class UnseenCount(BaseModel):
    unseen: int


@dataclass(frozen=True)
class Origin:
    """The chat an artifact is saved from, and its pixie for a pixie's chat or habit run."""

    session_id: str
    repo: str
    chat_title: str
    pixie_id: str | None


def checked_title(title: str) -> str:
    cleaned = " ".join(title.split())
    if not cleaned:
        msg = "an artifact needs a title"
        raise InvalidArtifactError(msg)
    if len(cleaned) > TITLE_MAX:
        msg = f"an artifact's title has at most {TITLE_MAX} characters"
        raise InvalidArtifactError(msg)
    return cleaned


def checked_content(content: str) -> bytes:
    """The content as the UTF-8 bytes saved for it."""
    if not content.strip():
        msg = "an artifact needs content"
        raise InvalidArtifactError(msg)
    try:
        data = content.encode()
    except UnicodeEncodeError as error:
        msg = "the content is not valid text (it has a lone surrogate)"
        raise InvalidArtifactError(msg) from error
    if len(data) > CONTENT_MAX:
        msg = (
            f"the content is {len(data)} bytes; an artifact version has at most"
            f" {CONTENT_MAX} bytes (1 MiB). Shorten it or split it into several artifacts."
        )
        raise InvalidArtifactError(msg)
    return data
