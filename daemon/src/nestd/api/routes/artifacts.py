"""Artifacts chats and pixies saved (B79). Content is served as JSON only: the daemon never
serves an HTML artifact as a page; clients show it in their own sandbox.
"""

from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from nestd.api.deps import Context, RequireDevice
from nestd.artifacts.models import Artifact, ArtifactDetail, UnseenCount, VersionContent

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


@router.post("/{artifact_id}/seen")
async def mark_seen(artifact_id: str, ctx: Context) -> Artifact:
    """Publishes `artifact.seen` when its latest version was unseen."""
    return await ctx.artifacts.mark_seen(artifact_id)


@router.delete("/{artifact_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_artifact(artifact_id: str, ctx: Context) -> Response:
    """Its every version, rows and files."""
    await ctx.artifacts.delete(artifact_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
