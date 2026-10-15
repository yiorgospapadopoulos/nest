"""Messages written into a running turn, and taking them back (B59).

Claude Code queues a user message that arrives while a turn runs, reads it at the turn's
next step (after a tool result) and echoes it under the uuid the message carried; when the
turn ends first, the message starts the next turn. Until it is read, the CLI's
`cancel_async_message` control request takes it off that queue. The SDK has no method for
it, so the request goes through the SDK's query, as for restoring files (IMP-02).
"""

import logging
from typing import Any, cast
from uuid import UUID

logger = logging.getLogger(__name__)


def engine_uuid(message_id: str) -> str:
    """The uuid a Nest message id (hex) carries to the engine, which wants the dashed form."""
    return str(UUID(message_id))


async def withdraw(client: object, uuid: str) -> bool:
    """Whether the engine took the message back; False when it already read it or cannot
    say, so the message is treated as read (its echo may follow).
    """
    query = getattr(client, "_query", None)
    if query is None:
        return False
    request = {"subtype": "cancel_async_message", "message_uuid": uuid}
    try:
        response: object = await query._send_control_request(request)
    except Exception as error:
        logger.warning("taking back a message from the agent failed (%s)", error)
        return False
    data = cast("dict[str, Any]", response) if isinstance(response, dict) else {}
    return data.get("cancelled") is True
