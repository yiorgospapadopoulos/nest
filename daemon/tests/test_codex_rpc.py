import asyncio

import pytest
from pydantic import JsonValue

from nestd.providers.codex_process import CodexLaunch
from nestd.providers.codex_rpc import (
    INTERNAL_ERROR,
    METHOD_NOT_FOUND,
    CodexClosedError,
    CodexRpc,
    CodexRpcError,
    JsonObject,
)
from tests.async_support import until
from tests.codex_support import FakeAppServer, FakeTransport


class Recorder:
    def __init__(self) -> None:
        self.notifications: list[tuple[str, JsonObject]] = []
        self.closed: list[str] = []
        self.answer: JsonValue = {"decision": "accept"}
        self.fail: Exception | None = None
        self.gate: asyncio.Event | None = None

    async def on_notification(self, method: str, params: JsonObject) -> None:
        if method == "boom":
            msg = "handler bug"
            raise RuntimeError(msg)
        self.notifications.append((method, params))

    async def on_request(self, method: str, params: JsonObject) -> JsonValue:
        if self.gate is not None:
            await self.gate.wait()
        if self.fail is not None:
            raise self.fail
        return self.answer

    async def on_closed(self, reason: str) -> None:
        self.closed.append(reason)


async def connect() -> tuple[FakeAppServer, FakeTransport, CodexRpc, Recorder]:
    server = FakeAppServer()
    transport = await server(CodexLaunch(("codex",), {}))
    recorder = Recorder()
    rpc = CodexRpc(transport, recorder.on_notification, recorder.on_request, recorder.on_closed)
    return server, transport, rpc, recorder


async def test_a_request_gets_its_answer_and_ids_count_up() -> None:
    server, _, rpc, _ = await connect()

    first = await rpc.request("initialize", {"clientInfo": {"name": "nest"}})
    await rpc.request("model/list", {})

    assert first["codexHome"] == "/codex-home"
    assert [m["id"] for m in server.sent] == [1, 2]
    assert "jsonrpc" not in server.sent[0]
    await rpc.close()


async def test_an_error_answer_raises_with_its_code_and_message() -> None:
    server, _, rpc, _ = await connect()
    server.errors["turn/steer"] = (-32600, "no active turn")

    with pytest.raises(CodexRpcError) as raised:
        await rpc.request("turn/steer", {})

    assert (raised.value.code, raised.value.message) == (-32600, "no active turn")
    await rpc.close()


async def test_an_error_answer_keeps_its_data() -> None:
    server, _, rpc, _ = await connect()
    server.errors["config/batchWrite"] = (-32600, "write failed")
    server.error_data["config/batchWrite"] = {"configWriteErrorCode": "configVersionConflict"}

    with pytest.raises(CodexRpcError) as raised:
        await rpc.request("config/batchWrite", {})

    assert raised.value.data == {"configWriteErrorCode": "configVersionConflict"}
    await rpc.close()


async def test_a_malformed_error_answer_still_raises() -> None:
    server, transport, rpc, _ = await connect()
    server.silent.add("x")
    waiting = asyncio.create_task(rpc.request("x", {}))
    await until(lambda: bool(server.sent))
    transport.push({"id": 1, "error": {"code": "bad", "message": 3}})

    with pytest.raises(CodexRpcError) as raised:
        await waiting

    assert raised.value.code == INTERNAL_ERROR
    assert raised.value.message == "Codex refused the request"
    assert raised.value.data is None
    await rpc.close()


async def test_answers_that_match_no_request_and_odd_lines_are_skipped() -> None:
    _, transport, rpc, recorder = await connect()
    transport.push({"id": 99, "result": {}})
    transport.push({"id": "text", "result": {}})
    transport.push_raw(b"not json\n")
    transport.push_raw(b"[1, 2]\n")
    transport.push({"method": "boom", "params": {}})
    transport.push({"method": "warning", "params": "not an object"})

    await until(lambda: bool(recorder.notifications))

    assert recorder.notifications == [("warning", {})]
    assert await rpc.request("model/list", {})
    await rpc.close()


async def test_a_result_that_is_not_an_object_reads_as_empty() -> None:
    server, _, rpc, _ = await connect()
    server.answers["thread/name/set"] = lambda _params: []  # type: ignore[assignment, return-value]

    assert await rpc.request("thread/name/set", {}) == {}
    await rpc.close()


async def test_a_late_second_answer_to_a_request_is_ignored() -> None:
    server, transport, rpc, _ = await connect()

    await rpc.request("model/list", {})
    transport.push({"id": 1, "result": {"again": True}})

    assert await rpc.request("model/list", {})
    assert len(server.requests("model/list")) == 2
    await rpc.close()


async def test_notifications_reach_the_handler_in_order() -> None:
    server, _, rpc, recorder = await connect()
    server.notify("turn/started", {"turn": {"id": "t"}})
    server.notify("item/agentMessage/delta", {"delta": "Hi"})

    await until(lambda: len(recorder.notifications) == 2)

    assert [method for method, _ in recorder.notifications] == [
        "turn/started",
        "item/agentMessage/delta",
    ]
    await rpc.close()


async def test_a_server_request_is_answered_with_the_handlers_result() -> None:
    server, _, rpc, _ = await connect()

    answer = await server.request("item/commandExecution/requestApproval", {"command": "ls"})

    assert answer == {"id": answer["id"], "result": {"decision": "accept"}}
    await rpc.close()


async def test_a_waiting_server_request_does_not_hold_up_notifications() -> None:
    server, _, rpc, recorder = await connect()
    recorder.gate = asyncio.Event()
    waiting = asyncio.create_task(server.request("item/fileChange/requestApproval", {}))
    server.notify("item/agentMessage/delta", {"delta": "streaming"})

    await until(lambda: bool(recorder.notifications))
    recorder.gate.set()

    assert (await waiting)["result"] == {"decision": "accept"}
    await rpc.close()


async def test_a_refused_server_request_is_answered_with_its_error() -> None:
    server, _, rpc, recorder = await connect()
    recorder.fail = CodexRpcError(METHOD_NOT_FOUND, "Nest does not support this")

    answer = await server.request("item/tool/call", {})

    assert answer["error"] == {"code": METHOD_NOT_FOUND, "message": "Nest does not support this"}
    await rpc.close()


async def test_a_failing_request_handler_answers_with_an_internal_error() -> None:
    server, _, rpc, recorder = await connect()
    recorder.fail = RuntimeError("bug")

    answer = await server.request("item/tool/call", {})

    assert answer["error"] == {"code": INTERNAL_ERROR, "message": "Nest failed"}
    await rpc.close()


async def test_the_server_ending_fails_pending_requests_and_says_why() -> None:
    server, transport, rpc, recorder = await connect()
    server.stderr = "panic: out of memory"
    server.silent.add("turn/start")
    waiting = asyncio.create_task(rpc.request("turn/start", {}))
    await until(lambda: bool(server.sent))
    transport.end()

    with pytest.raises(CodexClosedError, match="panic: out of memory"):
        await waiting

    await until(lambda: bool(recorder.closed))
    assert recorder.closed == ["Codex ended: panic: out of memory"]
    with pytest.raises(CodexClosedError):
        await rpc.request("model/list", {})
    await rpc.close()


async def test_a_read_failure_ends_the_connection_without_stderr() -> None:
    transport = await FakeAppServer()(CodexLaunch(("codex",), {}))
    recorder = Recorder()

    async def broken() -> bytes:
        msg = "pipe"
        raise OSError(msg)

    transport.readline = broken  # type: ignore[method-assign]
    rpc = CodexRpc(transport, recorder.on_notification, recorder.on_request, recorder.on_closed)

    await until(lambda: bool(recorder.closed))

    assert recorder.closed == ["Codex's output could not be read (OSError)"]
    assert rpc.ended == recorder.closed[0]


async def test_closing_cancels_waiting_server_requests_and_tells_no_one() -> None:
    server, transport, rpc, recorder = await connect()
    recorder.gate = asyncio.Event()
    asyncio.create_task(server.request("item/fileChange/requestApproval", {}))  # noqa: RUF006
    await until(lambda: bool(rpc._requests))  # pyright: ignore[reportPrivateUsage]

    await rpc.close()

    assert transport.closed
    assert recorder.closed == []
    assert rpc.ended == "Codex ended"


async def test_closing_without_an_on_closed_handler_is_quiet() -> None:
    server = FakeAppServer()
    transport = await server(CodexLaunch(("codex",), {}))
    recorder = Recorder()
    rpc = CodexRpc(transport, recorder.on_notification, recorder.on_request)

    transport.end()
    await until(lambda: rpc.ended is not None)

    await rpc.close()


async def test_an_answer_just_before_the_end_still_reaches_its_request() -> None:
    server, transport, rpc, _ = await connect()
    server.silent.add("model/list")
    waiting = asyncio.create_task(rpc.request("model/list", {}))
    await until(lambda: bool(server.sent))

    transport.push({"id": 1, "result": {"data": []}})
    transport.end()

    assert await waiting == {"data": []}
    await rpc.close()
