"""One Codex thread's notifications as the sink's calls (B91, D113).

Text and reasoning summaries stream as deltas, and each finished item is a message:
the agent's text, its reasoning as a thinking block, and tool items as calls with their
results (`codex_items`). `turn/completed` is the turn's result, with the tokens the turn
used. Rate limits are reported as Codex's usage windows (B91), apart from Claude's, and
kept for the reset time of a usage limit.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import ClassVar

from pydantic import JsonValue

from nestd.providers.base import (
    ContextUsage,
    HookOutput,
    LimitHit,
    McpServer,
    ProviderEventSink,
    ResultInfo,
    TextBlock,
    ThinkingBlock,
    TokenUsage,
)
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
COMPACTED = "Codex compacted the conversation to free up context."


class CodexStream:
    def __init__(self, sink: ProviderEventSink) -> None:
        self._sink = sink
        self.thread_id: str | None = None
        # The turn in progress, from its start until its end.
        self.turn_id: str | None = None
        # Messages written into the turn by their Nest id, until Codex reads them (B59).
        self.steered: set[str] = set()
        # File change items by id, for their approval requests.
        self.file_changes: dict[str, JsonObject] = {}
        # MCP tool calls in progress by item id, with their turn, for their approvals.
        self._mcp_calls: dict[str, tuple[str, JsonObject]] = {}
        self._reasoning: dict[str, int] = {}
        self._servers: dict[str, McpServer] = {}
        self._rate_limits: JsonObject = {}
        self._first_total: JsonObject | None = None
        self._first_last: JsonObject | None = None
        self._total: JsonObject | None = None
        self._last: JsonObject | None = None
        self._window: int | None = None
        self._limit: LimitHit | None = None

    def context_usage(self) -> ContextUsage | None:
        """The context the last request filled, of the model's window."""
        if self._last is None or not self._window:
            return None
        used = _count(self._last, "inputTokens") + _count(self._last, "outputTokens")
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
        thread = params.get("threadId")
        if self.thread_id is not None and isinstance(thread, str) and thread != self.thread_id:
            return  # another thread on this connection, such as a Codex subagent's
        handler = self._HANDLERS.get(method)
        if handler is not None:
            await handler(self, params)

    async def _turn_started(self, params: JsonObject) -> None:
        self.turn_id = text(obj(params.get("turn")).get("id")) or None
        self._first_total = self._first_last = None
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
        elif kind in TOOL_ITEMS:
            if kind == "fileChange":
                self.file_changes[item_id] = item
            elif kind == "mcpToolCall":
                self._mcp_calls[item_id] = (text(params.get("turnId")), item)
            await self._sink.message(list(tool_uses(item)), None)

    async def _item_completed(self, params: JsonObject) -> None:
        item = obj(params.get("item"))
        kind = item.get("type")
        item_id = text(item.get("id"))
        if kind == "agentMessage":
            body = text(item.get("text"))
            if body:
                await self._sink.message([TextBlock(text=body)], None)
        elif kind == "reasoning":
            started = self._reasoning.pop(item_id, None)
            # The summary, else the raw reasoning; often neither, which shows nothing.
            body = _joined(item.get("summary")) or _joined(item.get("content"))
            if body:
                block = ThinkingBlock(
                    text=body,
                    duration_ms=None
                    if started is None
                    else max(0, _ms(params.get("completedAtMs")) - started),
                )
                await self._sink.message([block], None)
            await self._sink.thinking(False)
        elif kind == "webSearch":
            await self._sink.message(list(tool_uses(item)), None)
            await self._sink.message(list(tool_results(item)), None)
        elif kind in TOOL_ITEMS:
            self.file_changes.pop(item_id, None)
            self._mcp_calls.pop(item_id, None)
            await self._sink.message(list(tool_results(item)), None)
        elif kind == "contextCompaction":
            await self._sink.notice("compacted", COMPACTED)

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
        self._total = obj(usage.get("total"))
        self._last = obj(usage.get("last"))
        window = usage.get("modelContextWindow")
        self._window = window if isinstance(window, int) else self._window
        if self._first_total is None and text(params.get("turnId")) == self.turn_id:
            self._first_total, self._first_last = self._total, self._last

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
            tokens=self._turn_tokens(),
        )
        # Over before the result, which takes back what Codex did not read (B59).
        self.turn_id = None
        self._reasoning.clear()
        self._mcp_calls.clear()
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

    def _turn_tokens(self) -> TokenUsage:
        """The turn's tokens: the thread's total since the turn's first report, plus that
        report's own request. Codex counts cached input in its input tokens.
        """
        if self._first_total is None or self._first_last is None or self._total is None:
            return TokenUsage()

        def turn(name: str) -> int:
            return max(
                0,
                _count(self._total or {}, name)
                - _count(self._first_total or {}, name)
                + _count(self._first_last or {}, name),
            )

        cached, written = turn("cachedInputTokens"), turn("cacheWriteInputTokens")
        return TokenUsage(
            input_tokens=max(0, turn("inputTokens") - cached - written),
            output_tokens=turn("outputTokens"),
            cache_read_input_tokens=cached,
            cache_creation_input_tokens=written,
        )

    _HANDLERS: ClassVar[dict[str, Callable[["CodexStream", JsonObject], Awaitable[None]]]] = {
        "turn/started": _turn_started,
        "turn/completed": _turn_completed,
        "item/started": _item_started,
        "item/completed": _item_completed,
        "item/agentMessage/delta": _text_delta,
        "item/reasoning/summaryTextDelta": _thinking_delta,
        "thread/tokenUsage/updated": _token_usage,
        "account/rateLimits/updated": _rate_limits_updated,
        "error": _error,
        "model/rerouted": _rerouted,
        "hook/completed": _hook_completed,
        "mcpServer/startupStatus/updated": _mcp_status,
    }


def _count(breakdown: JsonObject, name: str) -> int:
    value = breakdown.get(name)
    return value if isinstance(value, int) else 0


def _joined(parts: JsonValue | None) -> str:
    return "\n\n".join(part for part in (text(p) for p in items(parts)) if part)


def _ms(value: JsonValue | None) -> int:
    return value if isinstance(value, int) else 0
