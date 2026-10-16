"""Turns what a running agent reports into session events and turn boundaries.

The agent's run calls the sink from its reader; an error raised back would end the run as
if the agent had crashed, so each step is isolated and only logged (D048).
"""

from collections.abc import Awaitable
from typing import Literal, Protocol

from nestd.attachments.store import AttachmentStore
from nestd.config.models import PermissionMode
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import (
    AgentTask,
    CommandCatalog,
    EngineDetails,
    HookOutput,
    McpServer,
    MessageBlock,
    NoticeKind,
    ResultInfo,
    UsageInfo,
)
from nestd.sessions.bookkeeping import isolated, isolated_or
from nestd.sessions.hooks import SessionHooks
from nestd.sessions.live import LiveSession
from nestd.sessions.result_images import keep_images
from nestd.sessions.store import SessionStore
from nestd.sessions.subagents import PixieCalls

# A turn that ended without failing, whatever its result says: it made way for the next
# message (Send now, or Claude Code ending it holding that message), or the user stopped
# it. The result event carries the mark as `true`, and clients show no error for it (B59).
type TurnEnd = Literal["handoff", "stopped"]


class TurnEvents(Protocol):
    async def agent_active(self, live: LiveSession) -> None:
        """The agent produced output; starts a turn if none is in progress."""
        ...

    async def how_ended(self, live: LiveSession, info: ResultInfo) -> TurnEnd | None:
        """Why the turn ended when that was no failure, whatever its result says (B59)."""
        ...

    async def turn_finished(self, live: LiveSession, error: str | None, handoff: bool) -> None:
        """The turn's result arrived; `error` says why the engine ended it with an error,
        and `handoff` that it ended for the next message, as `how_ended` said.
        """
        ...

    async def run_stopped(self, live: LiveSession, error: str) -> None: ...

    async def background_tasks(self, live: LiveSession, running: int) -> None: ...

    async def permission_mode(self, live: LiveSession, mode: PermissionMode) -> None:
        """The engine reported its permission mode."""
        ...

    async def checkpoint(self, live: LiveSession, checkpoint_id: str) -> None:
        """The engine took the user message last given, under this checkpoint id."""
        ...

    async def message_taken(self, live: LiveSession, message_id: str, checkpoint_id: str) -> None:
        """The engine read a message written into the turn (B59)."""
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
        forking: str | None = None,
        attachments: AttachmentStore | None = None,
        calls: PixieCalls | None = None,
    ) -> None:
        """`forking` is the engine session the run cuts into a new one (B59): the cut is
        done once the run reports another session id. `attachments` keeps the images of
        tool results (B59); without it they are left out. `calls` records the pixies the
        run's agents call (B46, B70).
        """
        self._calls = calls
        self._forking = forking
        self._attachments = attachments
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
        if self._attachments is not None:
            await self._isolated(
                "the tool result images",
                keep_images(blocks, self._attachments, self._session_id),
            )
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
        if self._calls is not None:
            await self._isolated(
                "the pixie calls",
                self._calls.message(
                    self._session_id, self._live.run_agents, blocks, parent_tool_use_id
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

    async def thinking_delta(self, text: str, parent_tool_use_id: str | None) -> None:
        await self._delta(types.SESSION_THINKING_DELTA, text, parent_tool_use_id)

    async def subagent_delta(self, text: str, parent_tool_use_id: str) -> None:
        await self._delta(types.SESSION_SUBAGENT_DELTA, text, parent_tool_use_id)

    async def _delta(self, event_type: str, text: str, parent_tool_use_id: str | None) -> None:
        await self._isolated("starting a turn", self._turns.agent_active(self._live))
        await self._isolated(
            "the text event",
            self._bus.publish_ephemeral(
                event_type,
                {"text": text, "parent_tool_use_id": parent_tool_use_id},
                self._session_id,
            ),
        )

    async def hook(self, output: HookOutput) -> None:
        # Not agent output: SessionStart and Stop hooks speak outside a turn.
        await self._isolated(
            "the hook event",
            self._bus.publish(types.SESSION_HOOK, output.model_dump(mode="json"), self._session_id),
        )

    async def result(self, info: ResultInfo) -> None:
        self._retry_noted = False
        end = await isolated_or(
            "how the turn ended", self._session_id, self._turns.how_ended(self._live, info), None
        )
        payload = info.model_dump(mode="json")
        if end is not None:
            payload[end] = True
        await self._isolated(
            "the result event", self._bus.publish(types.SESSION_RESULT, payload, self._session_id)
        )
        await self._isolated(
            "the turn result hooks", self._hooks.turn_result(self._session_id, info)
        )
        await self._isolated(
            "ending the turn",
            self._turns.turn_finished(self._live, _error(info), end == "handoff"),
        )

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
        changes: dict[str, object] = {"provider_session_id": session_id}
        if self._forking is not None and session_id != self._forking:
            self._forking = None
            changes |= {"fork_from": None, "fork_at": None, "fork_drops": None}
        await self._store.update(self._session_id, **changes)

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

    async def message_taken(self, message_id: str, checkpoint_id: str) -> None:
        await self._isolated(
            "the message read in the turn",
            self._turns.message_taken(self._live, message_id, checkpoint_id),
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
        if self._calls is not None:
            await self._isolated(
                "the pixie calls", self._calls.task(self._session_id, self._live.run_agents, update)
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
