"""Turns what a running agent reports into session events and turn boundaries.

The agent's run calls the sink from its reader; an error raised back would end the run as
if the agent had crashed, so each step is isolated and only logged (D048).
"""

from collections.abc import Awaitable
from typing import Protocol

from harness.config.models import PermissionMode
from harness.events import types
from harness.events.bus import EventBus
from harness.providers.base import (
    AgentTask,
    CommandCatalog,
    EngineDetails,
    McpServer,
    MessageBlock,
    NoticeKind,
    ResultInfo,
    UsageInfo,
)
from harness.sessions.bookkeeping import isolated
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import LiveSession
from harness.sessions.store import SessionStore


class TurnEvents(Protocol):
    async def agent_active(self, live: LiveSession) -> None:
        """The agent produced output; starts a turn if none is in progress."""
        ...

    async def turn_finished(self, live: LiveSession, error: str | None) -> None:
        """The turn's result arrived; `error` says why the engine ended it with an error."""
        ...

    async def run_stopped(self, live: LiveSession, error: str) -> None: ...

    async def background_tasks(self, live: LiveSession, running: int) -> None: ...

    async def permission_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        """The engine reported its permission mode."""
        ...

    async def checkpoint(self, live: LiveSession, checkpoint_id: str) -> None:
        """The engine took the user message last given, under this checkpoint id."""
        ...


class SessionSink:
    def __init__(
        self,
        live: LiveSession,
        bus: EventBus,
        store: SessionStore,
        turns: TurnEvents,
        hooks: SessionHooks,
        provider_session_id: str | None,
    ) -> None:
        self._live = live
        self._session_id = live.session_id
        self._bus = bus
        self._store = store
        self._turns = turns
        self._hooks = hooks
        self._provider_session_id = provider_session_id
        # An API retry was noted in this turn; later ones are not (BUG-44).
        self._retry_noted = False

    async def message(self, blocks: list[MessageBlock], parent_tool_use_id: str | None) -> None:
        await self._isolated("starting a turn", self._turns.agent_active(self._live))
        await self._isolated(
            "the message event",
            self._bus.publish(
                types.SESSION_MESSAGE,
                {
                    "blocks": [block.model_dump(mode="json") for block in blocks],
                    "parent_tool_use_id": parent_tool_use_id,
                },
                self._session_id,
            ),
        )
        await self._isolated("the message hooks", self._hooks.message(self._session_id))

    async def text_delta(self, text: str) -> None:
        await self._isolated("starting a turn", self._turns.agent_active(self._live))
        await self._isolated(
            "the text event",
            self._bus.publish_ephemeral(types.SESSION_DELTA, {"text": text}, self._session_id),
        )

    async def thinking(self, active: bool) -> None:
        await self._isolated("starting a turn", self._turns.agent_active(self._live))
        await self._isolated(
            "the thinking event",
            self._bus.publish_ephemeral(
                types.SESSION_THINKING, {"active": active}, self._session_id
            ),
        )

    async def result(self, info: ResultInfo) -> None:
        self._retry_noted = False
        await self._isolated(
            "the result event",
            self._bus.publish(types.SESSION_RESULT, info.model_dump(mode="json"), self._session_id),
        )
        await self._isolated(
            "the turn result hooks", self._hooks.turn_result(self._session_id, info)
        )
        await self._isolated("ending the turn", self._turns.turn_finished(self._live, _error(info)))

    async def usage(self, info: UsageInfo) -> None:
        await self._isolated(
            "the usage event",
            self._bus.publish(types.USAGE_UPDATED, info.model_dump(mode="json")),
        )
        await self._isolated("the usage hooks", self._hooks.usage(info))

    async def connectors(self, servers: list[McpServer]) -> None:
        await self._isolated(
            "the connector report", self._hooks.connectors_reported(self._session_id, servers)
        )

    async def commands(self, catalog: CommandCatalog) -> None:
        await self._isolated(
            "the command report", self._hooks.commands_reported(self._session_id, catalog)
        )

    async def engine_details(self, details: EngineDetails) -> None:
        await self._isolated("the engine report", self._hooks.engine_reported(details))

    async def provider_session_id(self, session_id: str) -> None:
        if session_id != self._provider_session_id:
            earlier, self._provider_session_id = self._provider_session_id, session_id
            await self._isolated(
                "storing the agent's session id", self._store_provider_session(session_id, earlier)
            )

    async def _store_provider_session(self, session_id: str, earlier: str | None) -> None:
        # A cleared conversation (/clear) continues under a new id; the earlier one, and
        # its transcript, stay this session's (BUG-41).
        if earlier is not None:
            await self._store.keep_earlier_provider_session(self._session_id, earlier)
        await self._store.update(self._session_id, provider_session_id=session_id)

    async def notice(self, kind: NoticeKind, text: str) -> None:
        if kind == "api_retry":
            if self._retry_noted:
                return
            self._retry_noted = True
        await self._isolated(
            "the notice event",
            self._bus.publish(types.SESSION_NOTICE, {"kind": kind, "text": text}, self._session_id),
        )

    async def permission_mode(self, mode: PermissionMode) -> None:
        await self._isolated("the mode change", self._turns.permission_mode(self._live, mode))

    async def checkpoint(self, checkpoint_id: str) -> None:
        await self._isolated(
            "the message checkpoint", self._turns.checkpoint(self._live, checkpoint_id)
        )

    async def background_tasks(self, running: int) -> None:
        await self._isolated(
            "the background task count", self._turns.background_tasks(self._live, running)
        )

    async def task(self, update: AgentTask) -> None:
        # Not agent output: a background task can finish while the session is idle.
        await self._isolated(
            "the task event",
            self._bus.publish(
                types.SESSION_AGENT_TASK, update.model_dump(mode="json"), self._session_id
            ),
        )
        await self._isolated("the message hooks", self._hooks.message(self._session_id))

    async def stopped(self, error: str) -> None:
        await self._isolated("the run's end", self._turns.run_stopped(self._live, error))

    async def _isolated(self, kind: str, work: Awaitable[object]) -> None:
        await isolated(kind, self._session_id, work)


def _error(info: ResultInfo) -> str | None:
    """Why an error result ended the turn: the engine's first error, else its subtype."""
    if not info.is_error:
        return None
    return info.errors[0] if info.errors else info.subtype
