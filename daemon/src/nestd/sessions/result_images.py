"""Images in tool results become session attachments the clients fetch (B59).

The engine returns them as base64 data inside the result; storing them keeps the event
small and lets every client show them, and they are deleted with the session.
"""

import base64
import binascii
import logging
import mimetypes
from collections.abc import Sequence

from nestd.attachments.store import AttachmentStore
from nestd.errors import NestError
from nestd.providers.base import MessageBlock, ResultImage, ToolResultBlock

logger = logging.getLogger(__name__)


async def keep_images(
    blocks: Sequence[MessageBlock], attachments: AttachmentStore, session_id: str
) -> None:
    """Store each tool result's images and name them in its `images`. An image that cannot
    be kept (bad data, too large) is left out and logged.
    """
    for block in blocks:
        if not isinstance(block, ToolResultBlock):
            continue
        for number, image in enumerate(block.image_data, start=1):
            extension = mimetypes.guess_extension(image.media_type) or ""
            try:
                data = base64.b64decode(image.data, validate=True)
                attachment = await attachments.save(
                    f"tool-result-{number}{extension}", data, image.media_type
                )
            except (binascii.Error, NestError) as error:
                logger.warning(
                    "could not keep an image of tool result %s in session %s: %s",
                    block.tool_use_id,
                    session_id,
                    error,
                )
                continue
            await attachments.assign([attachment.id], session_id)
            block.images.append(
                ResultImage(attachment_id=attachment.id, media_type=attachment.media_type)
            )
