"""Saving, opening and deleting artifacts (B79), announced on the event bus: a card in the
transcript of the chat that saved one, and global events that keep clients' lists and the
unseen badge current.
"""

from dataclasses import dataclass

from pydantic import JsonValue

from nestd.artifacts.ask import AskAnswer, AskStatus, PageAsks
from nestd.artifacts.files import FileData, checked_files
from nestd.artifacts.kinds import checked_kind_content
from nestd.artifacts.models import (
    EDITABLE,
    Artifact,
    ArtifactDetail,
    ArtifactKind,
    ArtifactVersion,
    ForeignArtifactError,
    InvalidArtifactError,
    Origin,
    SaveAction,
    VersionContent,
    checked_content,
    checked_title,
)
from nestd.artifacts.storage import PageData, PageStorage
from nestd.artifacts.store import ArtifactStore
from nestd.events import types
from nestd.events.bus import EventBus


@dataclass(frozen=True)
class ReadArtifact:
    latest: VersionContent
    stored: PageData
    asks: AskStatus


class Artifacts:
    def __init__(
        self, store: ArtifactStore, bus: EventBus, storage: PageStorage, asks: PageAsks
    ) -> None:
        self._store = store
        self._bus = bus
        self._storage = storage
        self._asks = asks

    async def create(
        self,
        origin: Origin,
        kind: ArtifactKind,
        title: str,
        content: str,
        files: list[dict[str, JsonValue]] | None = None,
    ) -> Artifact:
        clean_title = checked_title(title)
        data = _checked(kind, content)
        checked = _checked_files(kind, files, len(data))
        artifact = await self._store.create(origin, kind, clean_title, data, checked)
        await self._saved(artifact, "created", origin.session_id)
        return artifact

    async def update(
        self,
        origin: Origin,
        artifact_id: str,
        content: str,
        title: str | None,
        files: list[dict[str, JsonValue]] | None = None,
    ) -> Artifact:
        """A new version of an artifact of the origin's chat, or of its pixie; complete in
        itself, so it has only the files it is given.
        """
        current = await self._owned(origin, artifact_id)
        data = _checked(current.kind, content)
        checked = _checked_files(current.kind, files, len(data))
        new_title = None if title is None else checked_title(title)
        artifact = await self._store.add_version(artifact_id, new_title, data, files=checked)
        await self._saved(artifact, "updated", origin.session_id)
        return artifact

    async def read(self, origin: Origin, artifact_id: str) -> ReadArtifact:
        """The latest version of an artifact the origin may update, with the user's edits,
        what its page stored and how often it asked Claude today.
        """
        current = await self._owned(origin, artifact_id)
        stored = await self._storage.read(artifact_id)
        latest = await self._store.content(artifact_id, current.latest_version, stored.items)
        return ReadArtifact(latest, stored, await self._asks.status(artifact_id))

    async def ask(self, artifact_id: str, prompt: str, system: str | None) -> AskAnswer:
        """The page asks Claude (B88), within its daily budget."""
        await self._store.get(artifact_id)
        return await self._asks.ask(artifact_id, prompt, system)

    async def ask_status(self, artifact_id: str) -> AskStatus:
        await self._store.get(artifact_id)
        return await self._asks.status(artifact_id)

    async def edit(self, artifact_id: str, content: str, base_version: int) -> ArtifactVersion:
        """The user's new version of a document, saved from the reader over `base_version`,
        which must still be the latest; announced like an agent's, as `edited`.
        """
        current = await self._store.get(artifact_id)
        if current.kind not in EDITABLE:
            msg = "Only documents can be edited"
            raise InvalidArtifactError(msg)
        data = _checked(current.kind, content)
        artifact = await self._store.add_version(
            artifact_id, None, data, author="user", base_version=base_version
        )
        await self._saved(artifact, "edited", artifact.session_id)
        detail = await self._store.detail(artifact_id)
        return detail.versions[-1]

    async def list_artifacts(
        self, repo: str | None = None, session_id: str | None = None, pixie_id: str | None = None
    ) -> list[Artifact]:
        return await self._store.list_artifacts(repo, session_id, pixie_id)

    async def detail(self, artifact_id: str) -> ArtifactDetail:
        return await self._store.detail(artifact_id)

    async def content(self, artifact_id: str, version: int) -> VersionContent:
        stored = await self._storage.read(artifact_id)
        return await self._store.content(artifact_id, version, stored.items)

    async def file(self, artifact_id: str, version: int, path: str) -> FileData:
        return await self._store.file(artifact_id, version, path)

    async def unseen(self) -> int:
        return await self._store.unseen()

    async def mark_seen(self, artifact_id: str) -> Artifact:
        artifact, changed = await self._store.mark_seen(artifact_id)
        if changed:
            await self._bus.publish(
                types.ARTIFACT_SEEN, {"artifact_id": artifact.id, **await self._unseen()}
            )
        return artifact

    async def delete(self, artifact_id: str) -> None:
        await self._store.delete(artifact_id)
        await self._bus.publish(
            types.ARTIFACT_DELETED, {"artifact_id": artifact_id, **await self._unseen()}
        )

    async def storage(self, artifact_id: str) -> PageData:
        await self._store.get(artifact_id)
        return await self._storage.read(artifact_id)

    async def write_storage(
        self,
        artifact_id: str,
        values: dict[str, str],
        remove: list[str],
        client: str | None = None,
    ) -> int:
        """What a page stored (B88), whole or not at all; its size after the write. Open
        pages on the user's other devices hear of it.
        """
        await self._store.get(artifact_id)
        size = await self._storage.write(artifact_id, values, remove)
        if values or remove:
            await self._storage_changed(artifact_id, values, remove, False, client)
        return size

    async def clear_storage(self, artifact_id: str, client: str | None = None) -> None:
        await self._store.get(artifact_id)
        await self._storage.clear(artifact_id)
        await self._storage_changed(artifact_id, {}, [], True, client)

    async def _storage_changed(
        self,
        artifact_id: str,
        values: dict[str, str],
        remove: list[str],
        clear: bool,
        client: str | None,
    ) -> None:
        await self._bus.publish_ephemeral(
            types.ARTIFACT_STORAGE,
            {
                "artifact_id": artifact_id,
                "set": dict[str, JsonValue](values),
                "remove": list[JsonValue](remove),
                "clear": clear,
                "client": client,
            },
        )

    async def _owned(self, origin: Origin, artifact_id: str) -> Artifact:
        current = await self._store.get(artifact_id)
        own_chat = current.session_id == origin.session_id
        own_pixie = origin.pixie_id is not None and current.pixie_id == origin.pixie_id
        if not (own_chat or own_pixie):
            msg = f"artifact {artifact_id!r} belongs to another chat; create a new one instead"
            raise ForeignArtifactError(msg)
        return current

    async def _saved(self, artifact: Artifact, action: SaveAction, session_id: str | None) -> None:
        version = artifact.latest_version
        if session_id is not None:
            await self._bus.publish(
                types.SESSION_ARTIFACT,
                {
                    "artifact_id": artifact.id,
                    "version": version,
                    "title": artifact.title,
                    "kind": artifact.kind,
                    "action": action,
                },
                session_id,
            )
        await self._bus.publish(
            types.ARTIFACT_SAVED,
            {
                "artifact": artifact.model_dump(mode="json"),
                "action": action,
                "version": version,
                **await self._unseen(),
            },
        )

    async def _unseen(self) -> dict[str, JsonValue]:
        return {"unseen": await self._store.unseen()}


def _checked(kind: ArtifactKind, content: str) -> bytes:
    data = checked_content(content)
    checked_kind_content(kind, content)
    return data


def _checked_files(
    kind: ArtifactKind, files: list[dict[str, JsonValue]] | None, content_size: int
) -> list[FileData]:
    if files is None:
        return []
    if kind != "html":
        msg = f"only html pages take files; a {kind} artifact cannot"
        raise InvalidArtifactError(msg)
    return checked_files(files, content_size)
