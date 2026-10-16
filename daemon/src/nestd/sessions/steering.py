"""Messages sent while a turn runs go into that turn, as in Claude Code (B59).

A message the running agent can take is stored in the queue marked sent and written into
the turn at once; the agent reads it at its next step, or starts its next turn with it, and
its echo removes it from the queue (the turn runner shows it then). Until the agent reads
it, the message can be taken back: to remove it, before a Stop or Send now, and when the
turn ends, so that a message the agent did not read waits in Nest's queue again. A message
the agent cannot take now (no run open, publishing, a Stop pressed, a new attachment
folder, another effort) waits in the queue for the turn's end, as before (D032).
"""

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from nestd.attachments.store import Attachment, AttachmentStore
from nestd.sessions.errors import MessageTakenError
from nestd.sessions.live import LiveSession
from nestd.sessions.models import QueuedMessage, Sender, Session
from nestd.sessions.queue import MessageQueue
from nestd.sessions.rules import user_input
from nestd.sessions.store import SessionStore

logger = logging.getLogger(__name__)

# Whether the live run can take a message whose files are in these folders as it is.
type RunFits = Callable[[LiveSession, Session, tuple[Path, ...]], Awaitable[bool]]
# A message's text as the agent gets it.
type AgentText = Callable[[LiveSession, str], Awaitable[str]]


class Steering:
    def __init__(
        self,
        store: SessionStore,
        queue: MessageQueue,
        attachments: AttachmentStore,
        fits: RunFits,
        agent_text: AgentText,
    ) -> None:
        self._agent_text = agent_text
        self._store = store
        self._queue = queue
        self._attachments = attachments
        self._fits = fits

    async def send(
        self, live: LiveSession, text: str, attachments: list[Attachment], sender: Sender
    ) -> QueuedMessage | None:
        """Store the message and write it into the running turn; None when it cannot go
        there now and must wait for the turn's end. Messages already waiting go first.
        """
        async with live.steering:
            if not _ready(live) or await self._queue.waiting(live.session_id):
                return None
            if not await self._fits_run(live, attachments):
                return None
            message = await self._queue.add(
                live.session_id, text, attachments, sender=sender, sent=True
            )
            if await self._write(live, message, attachments):
                return message
            return message.model_copy(update={"sent": False})

    async def flush(self, live: LiveSession) -> None:
        """Write the messages waiting for the turn into it, in order, while they can go:
        those sent while its message was being given to the agent, or held by a Stop.
        """
        async with live.steering:
            if not _ready(live):
                return
            for message in await self._queue.waiting(live.session_id):
                ids = [attachment.id for attachment in message.attachments]
                attachments = await self._attachments.for_session(ids, live.session_id)
                if not await self._fits_run(live, attachments):
                    return
                await self._queue.mark_sent(live.session_id, [message.id], True)
                if not await self._write(live, message, attachments):
                    return

    async def retract(self, live: LiveSession) -> list[str]:
        """Take back every sent message the agent has not read; they wait for a turn again.
        Returns the ones it has read and not echoed yet. The caller holds `live.steering`.
        """
        run = live.run
        withdrawn: list[str] = []
        taken: list[str] = []
        for message_id in await self._queue.sent_ids(live.session_id):
            if run is not None and not await run.withdraw(message_id):
                taken.append(message_id)
            else:
                withdrawn.append(message_id)
        await self._queue.mark_sent(live.session_id, withdrawn, False)
        return taken

    async def remove(self, live: LiveSession | None, session_id: str, message_id: str) -> None:
        """Remove a queued message; one in the running turn only while the agent has not
        read it (409 `message_taken` otherwise).
        """
        message = await self._queue.get(session_id, message_id)
        if message.sent and live is not None:
            async with live.steering:
                message = await self._queue.get(session_id, message_id)
                run = live.run
                if message.sent and run is not None and not await run.withdraw(message_id):
                    msg = "Claude already read this message, so it can no longer be removed"
                    raise MessageTakenError(msg)
        await self._queue.cancel(session_id, message_id)

    async def _fits_run(self, live: LiveSession, attachments: list[Attachment]) -> bool:
        session = await self._store.get(live.session_id)
        folders = tuple(a.path.parent for a in attachments if not a.is_image)
        return await self._fits(live, session, folders)

    async def _write(
        self, live: LiveSession, message: QueuedMessage, attachments: list[Attachment]
    ) -> bool:
        run = live.run
        assert run is not None  # noqa: S101 (checked by `_ready` under the same lock)
        try:
            text = await self._agent_text(live, message.text)
            await run.steer(user_input(text, attachments), message.id)
        except Exception as error:
            # The run is ending; the message waits for the next turn instead.
            logger.warning(
                "writing a message into the turn of %s failed (%s)", live.session_id, error
            )
            await self._queue.mark_sent(live.session_id, [message.id], False)
            return False
        return True


def _ready(live: LiveSession) -> bool:
    """Whether a turn runs on a live run that takes messages written into it, and nothing
    is ending it or holding the session: a Stop or Send now, its end being concluded,
    publishing, a restore of files, or closing.
    """
    run = live.run
    if run is None or not run.steers or not live.turn_active or live.task is not None:
        return False
    return not (
        live.interrupted
        or live.resume_queue
        or live.concluding
        or live.publishing
        or live.holding
        or live.stopped
    )
