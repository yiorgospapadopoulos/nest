"""Artifacts chats and pixies saved (B79). Content is served as JSON only: the daemon never
serves an HTML artifact as a page; clients show it in their own sandbox.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status
from pydantic import BaseModel, Field

from nestd.api.deps import Context, RequireDevice
from nestd.artifacts.ask import PROMPT_MAX, SYSTEM_MAX, AskAnswer, AskStatus
from nestd.artifacts.models import (
    Artifact,
    ArtifactDetail,
    ArtifactVersion,
    EditDocument,
    UnseenCount,
    VersionContent,
)
from nestd.artifacts.storage import PageData, StorageSize

# A client's own id for a storage write, echoed in `artifact.storage` so it can skip it.
type _Client = Annotated[str | None, Field(max_length=64)]


class StorageWrite(BaseModel):
    set: dict[str, str] = {}
    remove: list[str] = []
    client: _Client = None


router = APIRouter(prefix="/api/artifacts", dependencies=[RequireDevice])


@router.get("")
async def list_artifacts(
    ctx: Context,
    repo: str | None = None,
    session_id: str | None = None,
    pixie_id: str | None = None,
) -> list[Artifact]:
    """The most recently updated first, at most 500; filters left out match all."""
    return await ctx.artifacts.list_artifacts(repo, session_id, pixie_id)


@router.get("/unseen")
async def unseen(ctx: Context) -> UnseenCount:
    return UnseenCount(unseen=await ctx.artifacts.unseen())


@router.get("/{artifact_id}")
async def get_artifact(artifact_id: str, ctx: Context) -> ArtifactDetail:
    return await ctx.artifacts.detail(artifact_id)


@router.get("/{artifact_id}/versions/{version}")
async def version_content(
    artifact_id: str, version: Annotated[int, Path(ge=1)], ctx: Context
) -> VersionContent:
    return await ctx.artifacts.content(artifact_id, version)


@router.post("/{artifact_id}/versions")
async def edit_document(artifact_id: str, body: EditDocument, ctx: Context) -> ArtifactVersion:
    """The user's edit of a document, a new version by `user` (B88). 409 when `base_version`
    is no longer the latest; 422 for another kind or content an agent could not save either.
    """
    return await ctx.artifacts.edit(artifact_id, body.content, body.base_version)


@router.get("/{artifact_id}/storage")
async def page_storage(artifact_id: str, ctx: Context) -> PageData:
    """What the artifact's page stored (B88), for all its versions."""
    return await ctx.artifacts.storage(artifact_id)


@router.post("/{artifact_id}/storage")
async def write_page_storage(artifact_id: str, body: StorageWrite, ctx: Context) -> StorageSize:
    """Sets and removes keys at once, or nothing: 413 over a cap, 422 for a bad key."""
    size = await ctx.artifacts.write_storage(artifact_id, body.set, body.remove, body.client)
    return StorageSize(size=size)


@router.delete("/{artifact_id}/storage", status_code=status.HTTP_204_NO_CONTENT)
async def clear_page_storage(
    artifact_id: str, ctx: Context, client: Annotated[str | None, Query(max_length=64)] = None
) -> Response:
    await ctx.artifacts.clear_storage(artifact_id, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{artifact_id}/versions/{version}/files/{path:path}")
async def version_file(
    artifact_id: str, version: Annotated[int, Path(ge=1)], path: str, ctx: Context
) -> Response:
    """A file of a multi-file page (B88), always as a download, never shown inline."""
    file = await ctx.artifacts.file(artifact_id, version, path)
    name = file.path.rsplit("/", 1)[-1]
    return Response(
        file.data,
        media_type=file.mime,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


class AskRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=PROMPT_MAX)
    system: str | None = Field(default=None, max_length=SYSTEM_MAX)


@router.get("/{artifact_id}/ask")
async def ask_status(artifact_id: str, ctx: Context) -> AskStatus:
    """The page's asks today (B88), so a reader shows the count when it opens."""
    return await ctx.artifacts.ask_status(artifact_id)


@router.post("/{artifact_id}/ask")
async def ask(artifact_id: str, body: AskRequest, ctx: Context) -> AskAnswer:
    """The page asks Claude (B88): 403 when turned off, 429 `{detail, resets_at}` when
    today's asks are used, 409 while one runs for this artifact, 502 when Claude fails.
    """
    return await ctx.artifacts.ask(artifact_id, body.prompt, body.system)


@router.post("/{artifact_id}/seen")
async def mark_seen(artifact_id: str, ctx: Context) -> Artifact:
    """Publishes `artifact.seen` when its latest version was unseen."""
    return await ctx.artifacts.mark_seen(artifact_id)


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(artifact_id: str, ctx: Context) -> Response:
    """Its every version, rows and files."""
    await ctx.artifacts.delete(artifact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
