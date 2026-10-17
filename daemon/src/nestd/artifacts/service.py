"""Saving, opening and deleting artifacts (B79), announced on the event bus: a card in the
transcript of the chat that saved one, and global events that keep clients' lists and the
unseen badge current.
"""

from pydantic import JsonValue

from nestd.artifacts.models import (
    Artifact,
    ArtifactDetail,
    ArtifactKind,
    ForeignArtifactError,
    Origin,
    SaveAction,
    VersionContent,
    checked_content,
    checked_title,
)
from nestd.artifacts.store import ArtifactStore
from nestd.events import types
from nestd.events.bus import EventBus


class Artifacts:
    def __init__(self, store: ArtifactStore, bus: EventBus) -> None:
        self._store = store
        self._bus = bus

    async def create(
        self, origin: Origin, kind: ArtifactKind, title: str, content: str
    ) -> Artifact:
        artifact = await self._store.create(
            origin, kind, checked_title(title), checked_content(content)
        )
        await self._saved(artifact, "created", origin.session_id)
        return artifact

    async def update(
        self, origin: Origin, artifact_id: str, content: str, title: str | None
    ) -> Artifact:
        """A new version of an artifact of the origin's chat, or of its pixie."""
        current = await self._store.get(artifact_id)
        own_chat = current.session_id == origin.session_id
        own_pixie = origin.pixie_id is not None and current.pixie_id == origin.pixie_id
        if not (own_chat or own_pixie):
            msg = f"artifact {artifact_id!r} belongs to another chat; create a new one instead"
            raise ForeignArtifactError(msg)
        data = checked_content(content)
        new_title = None if title is None else checked_title(title)
        artifact = await self._store.add_version(artifact_id, new_title, data)
        await self._saved(artifact, "updated", origin.session_id)
        return artifact

    async def list_artifacts(
        self, repo: str | None = None, session_id: str | None = None, pixie_id: str | None = None
    ) -> list[Artifact]:
        return await self._store.list_artifacts(repo, session_id, pixie_id)

    async def detail(self, artifact_id: str) -> ArtifactDetail:
        return await self._store.detail(artifact_id)

    async def content(self, artifact_id: str, version: int) -> VersionContent:
        return await self._store.content(artifact_id, version)

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

    async def _saved(self, artifact: Artifact, action: SaveAction, session_id: str) -> None:
        version = artifact.latest_version
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
