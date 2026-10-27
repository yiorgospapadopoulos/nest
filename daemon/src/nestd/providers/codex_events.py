"""One Codex run's notifications as the sink's calls (B91, D113).

Text and reasoning summaries stream as deltas, and each finished item is a message:
the agent's text, its reasoning as a thinking block, and tool items as calls with their
results (`codex_items`). `turn/completed` is the turn's result, with the tokens the turn
used. Rate limits are reported as Codex's usage windows (B91), apart from Claude's, and
kept for the reset time of a usage limit. A plan update is the agent's whole task list
(B112), as Claude's TaskCreate and TaskUpdate keep it.

The connection also carries the threads of Codex's own subagents (B112, `codex_agents`):
their messages, deltas, plans and tokens go to the sink as a Claude subagent's do, under
the Agent call that started them.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import ClassVar, Literal

from pydantic import JsonValue

from nestd.providers.base import (
    ContextUsage,
    HookOutput,
    LimitHit,
    McpServer,
    PlanStep,
    ProviderEventSink,
    ResultInfo,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
)
from nestd.providers.codex_agents import COLLAB_ITEM, CodexAgents, Subthread
from nestd.providers.codex_items import (
    TOOL_ITEMS,
    items,
    obj,
    text,
    tool_results,
    tool_uses,
)
from nestd.providers.codex_limits import WINDOWS, codex_usage
from nestd.providers.codex_rpc import JsonObject

USAGE_LIMIT = "usageLimitExceeded"
_SUBTYPES = {"completed": "success", "interrupted": "interrupted", "failed": "error"}
# Codex's MCP startup states as the statuses Nest keeps for connectors.
_STARTUP = {"starting": "pending", "ready": "connected", "failed": "failed", "cancelled": "failed"}
_HOOK_OUTCOMES = {"completed": "success", "failed": "error", "blocked": "error"}
_STEPS: dict[str, Literal["pending", "in_progress", "completed"]] = {
    "pending": "pending",
    "inProgress": "in_progress",
    "completed": "completed",
}
COMPACTED = "Codex compacted the conversation to free up context."


class TurnTokens:
    """A thread's token reports, for what one turn used: the thread's total since the
    turn's first report, plus that report's own request.
    """

    def __init__(self) -> None:
        self._first_total: JsonObject | None = None
        self._first_last: JsonObject | None = None
        self.total: JsonObject | None = None
        self.last: JsonObject | None = None

    def start(self) -> None:
        self._first_total = self._first_last = None

    def report(self, usage: JsonObject, this_turn: bool) -> None:
        self.total = obj(usage.get("total"))
        self.last = obj(usage.get("last"))
        if self._first_total is None and this_turn:
            self._first_total, self._first_last = self.total, self.last

    def turn(self) -> TokenUsage:
        """The turn's tokens. Codex counts cached input in its input tokens."""
        if self._first_total is None or self._first_last is None or self.total is None:
            return TokenUsage()

        def used(name: str) -> int:
            return max(
                0,
                _count(self.total or {}, name)
                - _count(self._first_total or {}, name)
                + _count(self._first_last or {}, name),
            )

        cached, written = used("cachedInputTokens"), used("cacheWriteInputTokens")
        return TokenUsage(
            input_tokens=max(0, used("inputTokens") - cached - written),
            output_tokens=used("outputTokens"),
            cache_read_input_tokens=cached,
            cache_creation_input_tokens=written,
        )


class CodexStream:
    def __init__(self, sink: ProviderEventSink, agents: CodexAgents | None = None) -> None:
        self._sink = sink
        self.agents = agents or CodexAgents(sink)
        self._thread_id: str | None = None
        # The turn in progress, from its start until its end.
        self.turn_id: str | None = None
        # Messages written into the turn by their Nest id, until Codex reads them (B59).
        self.steered: set[str] = set()
        # File change items by id, of every thread, for their approval requests.
        self.file_changes: dict[str, JsonObject] = {}
        # MCP tool calls in progress by item id, with their turn, for their approvals.
        self._mcp_calls: dict[str, tuple[str, JsonObject]] = {}
        self._reasoning: dict[str, int] = {}
        self._servers: dict[str, McpServer] = {}
        self._rate_limits: JsonObject = {}
        self._tokens = TurnTokens()
        # Each subagent thread's token reports, by thread id.
        self._subthread_tokens: dict[str, TurnTokens] = {}
        self._window: int | None = None
        self._limit: LimitHit | None = None

    @property
    def thread_id(self) -> str | None:
        return self._thread_id

    @thread_id.setter
    def thread_id(self, value: str | None) -> None:
        self._thread_id = value
        self.agents.main = value

    def context_usage(self) -> ContextUsage | None:
        """The context the last request filled, of the model's window."""
        last = self._tokens.last
        if last is None or not self._window:
            return None
        used = _count(last, "inputTokens") + _count(last, "outputTokens")
        return ContextUsage(
            percent=min(100.0, 100 * used / self._window), used=used, limit=self._window
        )

    def mcp_call(self, server: str, turn_id: str) -> JsonObject | None:
        """The latest MCP tool call of `server` in progress in the turn."""
        for turn, item in reversed(self._mcp_calls.values()):
            if turn == turn_id and item.get("server") == server:
                return item
        return None

    async def handle(self, method: str, params: JsonObject) -> None:
        if method == "thread/started":
            await self.agents.thread_started(obj(params.get("thread")))
            return
        thread = params.get("threadId")
        if self.thread_id is not None and isinstance(thread, str) and thread != self.thread_id:
            subthread = self.agents.thread(thread)
            if subthread is None:
                # Not known yet, or one Codex runs for itself: held, and dropped if never.
                self.agents.hold(thread, method, params)
                return
            handler = self._SUBTHREAD_HANDLERS.get(method)
            if handler is not None:
                await handler(self, subthread, params)
            return
        main = self._HANDLERS.get(method)
        if main is not None:
            await main(self, params)

    async def _turn_started(self, params: JsonObject) -> None:
        self.turn_id = text(obj(params.get("turn")).get("id")) or None
        self._tokens.start()
        self._limit = None

    async def _item_started(self, params: JsonObject) -> None:
        item = obj(params.get("item"))
        kind = item.get("type")
        item_id = text(item.get("id"))
        if kind == "reasoning":
            self._reasoning[item_id] = _ms(params.get("startedAtMs"))
            await self._sink.thinking(True)
        elif kind == "userMessage":
            client_id = text(item.get("clientId"))
            if client_id in self.steered:
                self.steered.discard(client_id)
                await self._sink.message_taken(client_id, item_id)
        elif kind == COLLAB_ITEM:
            await self.agents.collab_started(item)
        elif kind in TOOL_ITEMS:
            await self._tool_started(item, text(params.get("turnId")), None)

    async def _item_completed(self, params: JsonObject) -> None:
        item = obj(params.get("item"))
        kind = item.get("type")
        if kind == "reasoning":
            started = self._reasoning.pop(text(item.get("id")), None)
            await self._thinking_block(item, started, params, None)
            await self._sink.thinking(False)
        elif kind == "contextCompaction":
            await self._sink.notice("compacted", COMPACTED)
        else:
            await self._item_done(item, None)

    async def _tool_started(self, item: JsonObject, turn_id: str, parent: str | None) -> None:
        kind = item.get("type")
        item_id = text(item.get("id"))
        if kind == "fileChange":
            self.file_changes[item_id] = item
        elif kind == "mcpToolCall":
            self._mcp_calls[item_id] = (turn_id, item)
        await self._sink.message(list(tool_uses(item)), parent)

    async def _item_done(self, item: JsonObject, parent: str | None) -> str:
        """A finished item of any thread; returns the agent's text, if it is that."""
        kind = item.get("type")
        item_id = text(item.get("id"))
        if kind == "agentMessage":
            body = text(item.get("text"))
            if body:
                await self._sink.message([TextBlock(text=body)], parent)
            return body
        if kind == "webSearch":
            await self._sink.message(list(tool_uses(item)), parent)
            await self._sink.message(list(tool_results(item)), parent)
        elif kind == COLLAB_ITEM:
            await self.agents.collab_completed(item)
        elif kind in TOOL_ITEMS:
            self.file_changes.pop(item_id, None)
            self._mcp_calls.pop(item_id, None)
            await self._sink.message(list(tool_results(item)), parent)
        return ""

    async def _thinking_block(
        self, item: JsonObject, started: int | None, params: JsonObject, parent: str | None
    ) -> None:
        # The summary, else the raw reasoning; often neither, which shows nothing.
        body = _joined(item.get("summary")) or _joined(item.get("content"))
        if body:
            block = ThinkingBlock(
                text=body,
                duration_ms=None
                if started is None
                else max(0, _ms(params.get("completedAtMs")) - started),
            )
            await self._sink.message([block], parent)

    async def _text_delta(self, params: JsonObject) -> None:
        delta = text(params.get("delta"))
        if delta:
            await self._sink.text_delta(delta)

    async def _thinking_delta(self, params: JsonObject) -> None:
        delta = text(params.get("delta"))
        if delta:
            await self._sink.thinking_delta(delta, None)

    async def _token_usage(self, params: JsonObject) -> None:
        usage = obj(params.get("tokenUsage"))
        window = usage.get("modelContextWindow")
        self._window = window if isinstance(window, int) else self._window
        self._tokens.report(usage, text(params.get("turnId")) == self.turn_id)

    async def _plan_updated(self, params: JsonObject) -> None:
        await self._sink.plan(_steps(params), None)

    async def _rate_limits_updated(self, params: JsonObject) -> None:
        snapshot = obj(params.get("rateLimits"))
        # A sparse update: what it leaves out keeps its last value.
        self._rate_limits |= {k: v for k, v in snapshot.items() if v is not None}
        info = codex_usage(self._rate_limits)
        if info is not None:
            await self._sink.usage(info)

    async def _error(self, params: JsonObject) -> None:
        error = obj(params.get("error"))
        if params.get("willRetry") is True:
            await self._sink.notice("api_retry", text(error.get("message")) or "Codex retries.")
        elif error.get("codexErrorInfo") == USAGE_LIMIT:
            await self._limit_hit()

    async def _turn_completed(self, params: JsonObject) -> None:
        turn = obj(params.get("turn"))
        status = text(turn.get("status"))
        error = obj(turn.get("error"))
        if error.get("codexErrorInfo") == USAGE_LIMIT:
            await self._limit_hit()
        message = text(error.get("message"))
        duration = turn.get("durationMs")
        info = ResultInfo(
            is_error=status == "failed",
            subtype=_SUBTYPES.get(status, status or "unknown"),
            duration_ms=duration if isinstance(duration, int) else 0,
            num_turns=1,
            errors=[message] if message else [],
            tokens=self._tokens.turn(),
        )
        # Over before the result, which takes back what Codex did not read (B59).
        self.turn_id = None
        self._reasoning.clear()
        self._mcp_calls.clear()
        # The agents it did not wait for go on in the background, as Claude's do.
        if self.thread_id is not None:
            await self.agents.caller_went_on(self.thread_id)
        await self._sink.result(info)
        self.steered.clear()

    async def _rerouted(self, params: JsonObject) -> None:
        source, target = text(params.get("fromModel")), text(params.get("toModel"))
        await self._sink.notice("model_fallback", f"Codex switched from {source} to {target}.")

    async def _hook_completed(self, params: JsonObject) -> None:
        run = obj(params.get("run"))
        entries = [text(obj(entry).get("text")) for entry in items(run.get("entries"))]
        output = "\n".join(entry for entry in entries if entry)
        message = text(run.get("statusMessage"))
        if not output and not message:
            return
        event = text(run.get("eventName"))
        event = event[:1].upper() + event[1:]
        await self._sink.hook(
            HookOutput(
                hook_id=text(run.get("id")) or None,
                hook_name=event,
                hook_event=event,
                outcome=_HOOK_OUTCOMES.get(text(run.get("status")), "cancelled"),  # pyright: ignore[reportArgumentType]
                system_message=message or None,
                output=output or None,
            )
        )

    async def _mcp_status(self, params: JsonObject) -> None:
        name = text(params.get("name"))
        status = _STARTUP.get(text(params.get("status")), "pending")
        self._servers[name] = McpServer(name, status, text(params.get("error")) or None)
        await self._sink.connectors(sorted(self._servers.values(), key=lambda s: s.name))

    async def _limit_hit(self) -> None:
        hit = LimitHit(cut_off=True)
        for key in ("primary", "secondary"):
            window = obj(self._rate_limits.get(key))
            used = window.get("usedPercent")
            if isinstance(used, int | float) and used >= 100:
                minutes = window.get("windowDurationMins")
                resets = window.get("resetsAt")
                hit = LimitHit(
                    window=WINDOWS.get(minutes) if isinstance(minutes, int) else None,
                    resets_at=datetime.fromtimestamp(resets, UTC)
                    if isinstance(resets, int)
                    else None,
                    cut_off=True,
                )
                break
        if self._limit is None:
            self._limit = hit
            await self._sink.limit_hit(hit)

    # A subagent's thread: the same items under its Agent call, and no turn result of its
    # own; its turn's end is its call's or task's end.

    async def _sub_turn_started(self, thread: Subthread, params: JsonObject) -> None:
        self._subthread_tokens.setdefault(thread.id, TurnTokens()).start()
        await self.agents.turn_started(thread, text(obj(params.get("turn")).get("id")))

    async def _sub_item_started(self, thread: Subthread, params: JsonObject) -> None:
        if thread.refused is not None:
            return
        item = obj(params.get("item"))
        kind = item.get("type")
        if kind == "reasoning":
            thread.reasoning[text(item.get("id"))] = _ms(params.get("startedAtMs"))
        elif kind == COLLAB_ITEM:
            await self.agents.collab_started(item)
        elif kind in TOOL_ITEMS:
            await self._tool_started(item, text(params.get("turnId")), thread.id)

    async def _sub_item_completed(self, thread: Subthread, params: JsonObject) -> None:
        if thread.refused is not None:
            return
        item = obj(params.get("item"))
        if item.get("type") == "reasoning":
            started = thread.reasoning.pop(text(item.get("id")), None)
            await self._thinking_block(item, started, params, thread.id)
            return
        body = await self._item_done(item, thread.id)
        if body:
            thread.report = body

    async def _sub_text_delta(self, thread: Subthread, params: JsonObject) -> None:
        delta = text(params.get("delta"))
        if delta and thread.refused is None:
            await self._sink.subagent_delta(delta, thread.id)

    async def _sub_thinking_delta(self, thread: Subthread, params: JsonObject) -> None:
        delta = text(params.get("delta"))
        if delta and thread.refused is None:
            await self._sink.thinking_delta(delta, thread.id)

    async def _sub_token_usage(self, thread: Subthread, params: JsonObject) -> None:
        this_turn = text(params.get("turnId")) == thread.turn_id
        self._subthread_tokens.setdefault(thread.id, TurnTokens()).report(
            obj(params.get("tokenUsage")), this_turn
        )

    async def _sub_plan_updated(self, thread: Subthread, params: JsonObject) -> None:
        if thread.refused is None:
            await self._sink.plan(_steps(params), thread.id)

    async def _sub_error(self, thread: Subthread, params: JsonObject) -> None:
        if obj(params.get("error")).get("codexErrorInfo") == USAGE_LIMIT:
            await self._limit_hit()

    async def _sub_turn_completed(self, thread: Subthread, params: JsonObject) -> None:
        turn = obj(params.get("turn"))
        turn_id = text(turn.get("id"))
        error = obj(turn.get("error"))
        if error.get("codexErrorInfo") == USAGE_LIMIT:
            await self._limit_hit()
        tokens = self._subthread_tokens.setdefault(thread.id, TurnTokens()).turn()
        if thread.refused is None and tokens != TokenUsage():
            # Not in the run's own turn result; its id counts it once (B84).
            await self._sink.subagent_usage(f"{thread.id}:{turn_id}", tokens)
        await self.agents.turn_completed(
            thread, text(turn.get("status")), text(error.get("message"))
        )

    _HANDLERS: ClassVar[dict[str, Callable[["CodexStream", JsonObject], Awaitable[None]]]] = {
        "turn/started": _turn_started,
        "turn/completed": _turn_completed,
        "item/started": _item_started,
        "item/completed": _item_completed,
        "item/agentMessage/delta": _text_delta,
        "item/reasoning/summaryTextDelta": _thinking_delta,
        "thread/tokenUsage/updated": _token_usage,
        "turn/plan/updated": _plan_updated,
        "account/rateLimits/updated": _rate_limits_updated,
        "error": _error,
        "model/rerouted": _rerouted,
        "hook/completed": _hook_completed,
        "mcpServer/startupStatus/updated": _mcp_status,
    }
    _SUBTHREAD_HANDLERS: ClassVar[
        dict[str, Callable[["CodexStream", Subthread, JsonObject], Awaitable[None]]]
    ] = {
        "turn/started": _sub_turn_started,
        "turn/completed": _sub_turn_completed,
        "item/started": _sub_item_started,
        "item/completed": _sub_item_completed,
        "item/agentMessage/delta": _sub_text_delta,
        "item/reasoning/summaryTextDelta": _sub_thinking_delta,
        "thread/tokenUsage/updated": _sub_token_usage,
        "turn/plan/updated": _sub_plan_updated,
        "error": _sub_error,
    }


def _steps(params: JsonObject) -> list[PlanStep]:
    return [
        PlanStep(
            text=text(step.get("step")), status=_STEPS.get(text(step.get("status")), "pending")
        )
        for step in (obj(entry) for entry in items(params.get("plan")))
        if text(step.get("step"))
    ]


def _count(breakdown: JsonObject, name: str) -> int:
    value = breakdown.get(name)
    return value if isinstance(value, int) else 0


def _joined(parts: JsonValue | None) -> str:
    return "\n\n".join(part for part in (text(p) for p in items(parts)) if part)


def _ms(value: JsonValue | None) -> int:
    return value if isinstance(value, int) else 0
