from fastapi import APIRouter, Response, UploadFile, status
from fastapi.responses import FileResponse

from nestd.api.deps import Context, RequireDevice
from nestd.attachments.store import MAX_ATTACHMENT_BYTES, Attachment

SAFE_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "sandbox; default-src 'none'",
}

router = APIRouter(prefix="/api/attachments", dependencies=[RequireDevice])


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model_exclude={"path", "session_id"},
)
async def upload(file: UploadFile, ctx: Context) -> Attachment:
    # One byte more than the limit is enough to know the file is too large.
    data = await file.read(MAX_ATTACHMENT_BYTES + 1)
    return await ctx.attachments.save(file.filename or "file", data, file.content_type)


@router.get("/{attachment_id}")
async def download(attachment_id: str, ctx: Context) -> FileResponse:
    """An attachment's file: one the user sent, or an image a tool returned (B59)."""
    attachment = await ctx.attachments.get(attachment_id)
    # Only raster images display inline; anything else (HTML, SVG) downloads, and nothing
    # served here may run as a page on the daemon's origin.
    inline = attachment.is_image
    return FileResponse(
        attachment.path,
        media_type=attachment.media_type if inline else "application/octet-stream",
        filename=attachment.filename,
        content_disposition_type="inline" if inline else "attachment",
        headers=SAFE_HEADERS,
    )


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(attachment_id: str, ctx: Context) -> Response:
    """Delete an attachment and its file (Settings, Storage); 404 for an unknown one.
    Transcripts that showed it get a 404 for its file from then on.
    """
    await ctx.attachments.delete(attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
