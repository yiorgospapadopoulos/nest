"""What an artifact is on the wire (B79), and the limits of what an agent may save."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from nestd.errors import ConflictError, InvalidInputError, NotFoundError

# Markdown and HTML are shown as the agent wrote them; Nest builds the page of the four
# ready-made kinds from the data an agent sends (B88).
type ArtifactKind = Literal["markdown", "html", "slides", "document", "design", "design_system"]
KINDS: tuple[ArtifactKind, ...] = (
    "markdown",
    "html",
    "slides",
    "document",
    "design",
    "design_system",
)
EXTENSIONS: dict[ArtifactKind, str] = {
    "markdown": "md",
    "html": "html",
    "slides": "md",
    "document": "md",
    "design": "json",
    "design_system": "json",
}
# Only documents are edited by the user, in the reader (B88).
EDITABLE: tuple[ArtifactKind, ...] = ("document",)
TITLE_MAX = 200
# Bytes of a version's UTF-8 content.
CONTENT_MAX = 1024 * 1024
# Artifacts a listing returns at most, the most recently updated first.
LIST_MAX = 500

# Who saved a version: the chat's agent, or the user editing a document in the reader.
type Author = Literal["agent", "user"]
type SaveAction = Literal["created", "updated", "edited"]


class ArtifactNotFoundError(NotFoundError):
    pass


class InvalidArtifactError(InvalidInputError):
    pass


class ForeignArtifactError(ConflictError):
    """An agent tried to update an artifact of another chat or pixie."""


class StaleVersionError(ConflictError):
    """The user saved an edit of a version that is no longer the latest."""


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
    author: Author


class ArtifactDetail(Artifact):
    # Oldest first.
    versions: list[ArtifactVersion]


class PageFile(BaseModel):
    """A file of a version of a multi-file HTML page (B88), as a client lists it."""

    path: str
    size: int
    mime: str


class VersionContent(BaseModel):
    artifact_id: str
    version: int
    kind: ArtifactKind
    title: str
    # As saved.
    content: str
    # The whole document a client shows in its sandbox (B82): an HTML artifact with its
    # files inlined, or the page Nest's template builds; with what the page stored (B88).
    page: str
    size: int
    created_at: datetime
    author: Author
    # The files of a multi-file HTML page (B88), whose bytes the page also carries.
    files: list[PageFile]


class EditDocument(BaseModel):
    """The user's whole new Markdown of a document, edited from `base_version`."""

    content: str
    base_version: int = Field(ge=1)


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
