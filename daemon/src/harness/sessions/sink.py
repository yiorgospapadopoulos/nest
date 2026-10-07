"""Turns what a running agent reports into session events and turn boundaries."""

from typing import Protocol

from harness.events import types
from harness.events.bus import EventBus
from harness.providers.base import (
    AgentTask,
    CommandCatalog,
    EngineDetails,
    McpServer,
    MessageBlock,
    ResultInfo,
    UsageInfo,
)
from harness.sessions.hooks import SessionHooks
from harness.sessions.live import LiveSession
from harness.sessions.store import SessionStore


class TurnEvents(Protocol):
    async def agent_active(self, live: LiveSession) -> None:
        """The agent produced output; starts a turn if none is in progress."""
        ...

    async def turn_finished(self, live: LiveSession) -> None: ...

    async def run_stopped(self, live: LiveSession, error: str) -> None: ...

    async def background_tasks(self, live: LiveSession, running: int) -> None: ...


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

    async def message(self, blocks: list[MessageBlock], parent_tool_use_id: str | None) -> None:
        await self._turns.agent_active(self._live)
        await self._bus.publish(
            types.SESSION_MESSAGE,
            {
                "blocks": [block.model_dump(mode="json") for block in blocks],
                "parent_tool_use_id": parent_tool_use_id,
            },
            self._session_id,
        )
        await self._hooks.message(self._session_id)

    async def text_delta(self, text: str) -> None:
        await self._turns.agent_active(self._live)
        await self._bus.publish_ephemeral(types.SESSION_DELTA, {"text": text}, self._session_id)

    async def thinking(self, active: bool) -> None:
        await self._turns.agent_active(self._live)
        await self._bus.publish_ephemeral(
            types.SESSION_THINKING, {"active": active}, self._session_id
        )

    async def result(self, info: ResultInfo) -> None:
        await self._bus.publish(
            types.SESSION_RESULT, info.model_dump(mode="json"), self._session_id
        )
        await self._hooks.turn_result(self._session_id, info)
        await self._turns.turn_finished(self._live)

    async def usage(self, info: UsageInfo) -> None:
        await self._bus.publish(types.USAGE_UPDATED, info.model_dump(mode="json"))
        await self._hooks.usage(info)

    async def connectors(self, servers: list[McpServer]) -> None:
        await self._hooks.connectors_reported(self._session_id, servers)

    async def commands(self, catalog: CommandCatalog) -> None:
        await self._hooks.commands_reported(self._session_id, catalog)

    async def engine_details(self, details: EngineDetails) -> None:
        await self._hooks.engine_reported(details)

    async def provider_session_id(self, session_id: str) -> None:
        if session_id != self._provider_session_id:
            self._provider_session_id = session_id
            await self._store.update(self._session_id, provider_session_id=session_id)

    async def background_tasks(self, running: int) -> None:
        await self._turns.background_tasks(self._live, running)

    async def task(self, update: AgentTask) -> None:
        # Not agent output: a background task can finish while the session is idle.
        await self._bus.publish(
            types.SESSION_AGENT_TASK, update.model_dump(mode="json"), self._session_id
        )
        await self._hooks.message(self._session_id)

    async def stopped(self, error: str) -> None:
        await self._turns.run_stopped(self._live, error)
