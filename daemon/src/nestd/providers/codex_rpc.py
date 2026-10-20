"""A JSON-RPC client for `codex app-server` over its stdin and stdout (B91, D113).

The app-server speaks newline-delimited JSON-RPC 2.0 without the "jsonrpc" field. Nest
sends requests and notifications; the server answers them, sends notifications of its own,
and sends requests (approvals) that Nest answers. One reader takes every line for the life
of the connection: notifications are handled in order on it, and each server request in a
task of its own, since an approval can wait for the user while the turn streams on.
"""

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Protocol, cast

from pydantic import JsonValue

logger = logging.getLogger(__name__)

# JSON-RPC's codes for a method the receiver lacks and for its own failure.
METHOD_NOT_FOUND = -32601
INTERNAL_ERROR = -32603

type JsonObject = dict[str, JsonValue]
type NotificationHandler = Callable[[str, JsonObject], Awaitable[None]]
# Returns the result to answer with; raises CodexRpcError to answer with an error.
type RequestHandler = Callable[[str, JsonObject], Awaitable[JsonValue]]
# Told why the connection ended when the server went away on its own.
type ClosedHandler = Callable[[str], Awaitable[None]]


class CodexRpcError(Exception):
    """An error answer to a request, from the server or for it."""

    def __init__(self, code: int, message: str, data: JsonValue = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        # The error's `data`, such as the kind of a config write failure.
        self.data = data


class CodexClosedError(Exception):
    """The app-server ended, or the connection was closed, before the answer came."""


class Transport(Protocol):
    """Lines to and from the app-server; tests substitute an in-memory one."""

    async def write(self, line: bytes) -> None: ...

    async def readline(self) -> bytes:
        """The next line; empty at the end of the server's output."""
        ...

    async def close(self) -> None:
        """End the server and wait for it."""
        ...

    def stderr(self) -> str:
        """The end of what the server wrote to stderr, for a crash's message."""
        ...


class CodexRpc:
    def __init__(
        self,
        transport: Transport,
        on_notification: NotificationHandler,
        on_request: RequestHandler,
        on_closed: ClosedHandler | None = None,
    ) -> None:
        self._transport = transport
        self._on_notification = on_notification
        self._on_request = on_request
        self._on_closed = on_closed
        self._next_id = 0
        self._pending: dict[int, asyncio.Future[JsonObject]] = {}
        self._requests: set[asyncio.Task[None]] = set()
        self._write_lock = asyncio.Lock()
        self._closing = False
        self._ended: str | None = None
        self._reader = asyncio.create_task(self._read())

    @property
    def ended(self) -> str | None:
        """Why the connection ended; None while it is open."""
        return self._ended

    async def request(self, method: str, params: JsonObject) -> JsonObject:
        if self._ended is not None:
            raise CodexClosedError(self._ended)
        self._next_id += 1
        request_id = self._next_id
        answer = asyncio.get_running_loop().create_future()
        self._pending[request_id] = answer
        try:
            await self._write({"id": request_id, "method": method, "params": params})
            return await answer
        finally:
            self._pending.pop(request_id, None)

    async def notify(self, method: str, params: JsonObject) -> None:
        await self._write({"method": method, "params": params})

    async def close(self) -> None:
        """End the server and wait for it; pending requests fail."""
        self._closing = True
        for task in list(self._requests):
            task.cancel()
        await asyncio.gather(*self._requests, return_exceptions=True)
        with suppress(Exception):
            await self._transport.close()
        await asyncio.gather(self._reader, return_exceptions=True)

    async def _write(self, message: JsonObject) -> None:
        line = json.dumps(message, separators=(",", ":")).encode() + b"\n"
        async with self._write_lock:
            await self._transport.write(line)

    async def _read(self) -> None:
        reason = "Codex ended"
        try:
            while line := await self._transport.readline():
                await self._handle(line)
        except Exception as error:
            reason = f"Codex's output could not be read ({type(error).__name__})"
        tail = self._transport.stderr()
        self._ended = f"{reason}: {tail}" if tail else reason
        for answer in self._pending.values():
            if not answer.done():
                answer.set_exception(CodexClosedError(self._ended))
        if self._on_closed is not None and not self._closing:
            await self._on_closed(self._ended)

    async def _handle(self, line: bytes) -> None:
        try:
            raw: object = json.loads(line)
        except ValueError:
            logger.warning("Codex wrote a line that is not JSON; it is skipped")
            return
        if not isinstance(raw, dict):
            logger.warning("Codex wrote a JSON value that is not an object; it is skipped")
            return
        message = cast("JsonObject", raw)
        method = message.get("method")
        params = _object(message.get("params"))
        if isinstance(method, str) and "id" in message:
            task = asyncio.create_task(self._answer(message["id"], method, params))
            self._requests.add(task)
            task.add_done_callback(self._requests.discard)
        elif isinstance(method, str):
            try:
                await self._on_notification(method, params)
            except Exception:
                logger.exception("handling Codex's %s notification failed", method)
        else:
            self._resolve(message)

    def _resolve(self, message: JsonObject) -> None:
        request_id = message.get("id")
        answer = self._pending.get(request_id) if isinstance(request_id, int) else None
        if answer is None or answer.done():
            return
        error = message.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            text = error.get("message")
            answer.set_exception(
                CodexRpcError(
                    code if isinstance(code, int) else INTERNAL_ERROR,
                    text if isinstance(text, str) else "Codex refused the request",
                    error.get("data"),
                )
            )
            return
        answer.set_result(_object(message.get("result")))

    async def _answer(self, request_id: JsonValue, method: str, params: JsonObject) -> None:
        try:
            result = await self._on_request(method, params)
            reply: JsonObject = {"id": request_id, "result": result}
        except CodexRpcError as error:
            reply = {"id": request_id, "error": {"code": error.code, "message": error.message}}
        except Exception:
            logger.exception("answering Codex's %s request failed", method)
            reply = {"id": request_id, "error": {"code": INTERNAL_ERROR, "message": "Nest failed"}}
        with suppress(Exception):
            await self._write(reply)


def _object(value: JsonValue | None) -> JsonObject:
    return cast("JsonObject", value) if isinstance(value, dict) else {}
