from fastapi import APIRouter, UploadFile, status

from harness.api.deps import Context, RequireDevice
from harness.attachments.store import MAX_ATTACHMENT_BYTES, Attachment

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
