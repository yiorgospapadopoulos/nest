"""The translator routes: Claude Code and Codex talk to a chat-completions-only server."""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from nestd.api.routes import local_proxy
from nestd.local.run import PLACEHOLDER_KEY
from nestd.local.translate.upstream import Upstream
from nestd.local.translate.values import JsonObject, obj, string
from tests.test_local_translate_stream import call, delta

KEY = "translator-key"
BASE = "http://192.168.1.20:1234"
LOCAL = ("127.0.0.1", 50000)
AUTH = {"x-api-key": KEY}
CHAT_URL = f"{BASE}/v1/chat/completions"

type Handler = Callable[[httpx.Request], httpx.Response]


def sse(*chunks: JsonObject) -> bytes:
    return (
        b"".join(f"data: {json.dumps(chunk)}\n\n".encode() for chunk in chunks)
        + b"data: [DONE]\n\n"
    )


def streamed(*chunks: JsonObject) -> Handler:
    return lambda _request: httpx.Response(
        200, content=sse(*chunks), headers={"content-type": "text/event-stream"}
    )


class BrokenStream(httpx.AsyncByteStream):
    def __init__(self, first: bytes) -> None:
        self._first = first

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield self._first
        raise httpx.ReadError("connection reset")


@dataclass
class FakeServer:
    replies: list[Handler] = field(default_factory=list[Handler])
    requests: list[httpx.Request] = field(default_factory=list[httpx.Request])

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.replies.pop(0)(request)

    def body(self, index: int = -1) -> JsonObject:
        return json.loads(self.requests[index].content)


@dataclass
class Proxy:
    client: TestClient
    upstream: FakeServer


def make_proxy(
    upstream_key: str | None = "server-key", peer: tuple[str, int] = LOCAL, configure: bool = True
) -> Proxy:
    """`srv` speaks only Chat Completions; `native` speaks Anthropic Messages itself, and
    `lms` does too but counts cache reads in its input tokens, as LM Studio does."""
    upstream = FakeServer()

    async def resolve(server_id: str) -> Upstream | None:
        if server_id not in ("srv", "native", "lms"):
            return None
        return Upstream(
            BASE,
            upstream_key,
            messages=server_id != "srv",
            usage_counts_cache=server_id == "lms",
            app="LM Studio" if server_id == "lms" else None,
            contexts={"qwen3-coder": 8192, "org/qwen3-coder": 8192} if server_id == "lms" else {},
        )

    app = FastAPI()
    app.include_router(local_proxy.router)
    if configure:
        local_proxy.configure(
            app, resolve=resolve, key=KEY, transport=httpx.MockTransport(upstream.handle)
        )
    return Proxy(TestClient(app, client=peer), upstream)


@pytest.fixture
def proxy() -> Proxy:
    return make_proxy()


def events(text: str) -> list[tuple[str, JsonObject]]:
    found: list[tuple[str, JsonObject]] = []
    for frame in text.strip().split("\n\n"):
        name_line, data_line = frame.split("\n")
        found.append(
            (name_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))
        )
    return found


def messages_body(**extra: object) -> JsonObject:
    body: JsonObject = {
        "model": "qwen3-coder",
        "max_tokens": 1024,
        "stream": True,
        "system": [{"type": "text", "text": "You are Claude Code."}],
        "messages": [{"role": "user", "content": "Write hello.txt"}],
        "tools": [
            {"name": "Write", "description": "Write a file", "input_schema": {"type": "object"}}
        ],
    }
    body.update(json.loads(json.dumps(extra)))
    return body


USAGE: JsonObject = {"choices": [], "usage": {"prompt_tokens": 1500, "completion_tokens": 10}}


def test_a_streamed_text_reply_comes_back_as_anthropic_events(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        streamed(delta({"role": "assistant", "content": "Done."}), delta({}, "stop"), USAGE)
    )
    response = proxy.client.post(
        "/local/srv/v1/messages?beta=true", json=messages_body(), headers=AUTH
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    found = events(response.text)
    assert [name for name, _ in found] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert found[2][1]["delta"] == {"type": "text_delta", "text": "Done."}
    assert found[4][1]["usage"] == {"input_tokens": 1500, "output_tokens": 10}
    request = proxy.upstream.requests[0]
    assert str(request.url) == CHAT_URL
    assert request.headers["authorization"] == "Bearer server-key"
    assert proxy.upstream.body() == {
        "model": "qwen3-coder",
        "messages": [
            {"role": "system", "content": "You are Claude Code."},
            {"role": "user", "content": "Write hello.txt"},
        ],
        "max_tokens": 1024,
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "Write",
                    "description": "Write a file",
                    "parameters": {"type": "object"},
                },
            }
        ],
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_a_tool_call_round_trip(proxy: Proxy) -> None:
    arguments = json.dumps({"file_path": "/work/hello.txt", "content": "hi"})
    proxy.upstream.replies.append(
        streamed(
            delta({"tool_calls": [call(0, "call_1", "Write", arguments[:12])]}),
            delta({"tool_calls": [call(0, arguments=arguments[12:])]}),
            delta({}, "tool_calls"),
            USAGE,
        )
    )
    first = proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)
    found = events(first.text)
    assert found[1][1]["content_block"] == {
        "type": "tool_use",
        "id": "call_1",
        "name": "Write",
        "input": {},
    }
    partial = "".join(
        string(obj(data["delta"]).get("partial_json"))
        for name, data in found
        if name == "content_block_delta"
    )
    assert json.loads(partial) == {"file_path": "/work/hello.txt", "content": "hi"}
    assert found[-2][1]["delta"] == {"stop_reason": "tool_use", "stop_sequence": None}

    proxy.upstream.replies.append(streamed(delta({"content": "Written."}), delta({}, "stop")))
    follow_up = messages_body(
        messages=[
            {"role": "user", "content": "Write hello.txt"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call_1",
                        "name": "Write",
                        "input": json.loads(arguments),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "call_1", "content": "Wrote it"}
                ],
            },
        ]
    )
    second = proxy.client.post("/local/srv/v1/messages", json=follow_up, headers=AUTH)
    assert second.status_code == 200
    sent = proxy.upstream.body()["messages"]
    assert isinstance(sent, list)
    assert sent[-2:] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "Write", "arguments": arguments},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "Wrote it"},
    ]


def test_without_a_server_key_no_authorization_goes_upstream() -> None:
    proxy = make_proxy(upstream_key=None)
    proxy.upstream.replies.append(streamed(delta({"content": "x"})))
    proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)
    assert "authorization" not in proxy.upstream.requests[0].headers


def test_a_non_streaming_message(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Mock title"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 30, "completion_tokens": 3},
            },
        )
    )
    response = proxy.client.post(
        "/local/srv/v1/messages", json=messages_body(stream=False), headers=AUTH
    )
    assert response.status_code == 200
    message = response.json()
    assert message["content"] == [{"type": "text", "text": "Mock title"}]
    assert message["stop_reason"] == "end_turn"
    assert message["usage"] == {"input_tokens": 30, "output_tokens": 3}
    assert proxy.upstream.body()["stream"] is False


def test_a_non_streaming_reply_that_is_not_json_is_a_bad_gateway(proxy: Proxy) -> None:
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, content=b"<html>"))
    response = proxy.client.post(
        "/local/srv/v1/messages", json=messages_body(stream=False), headers=AUTH
    )
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "api_error"


def test_a_non_streaming_reply_cut_off_midway_is_a_bad_gateway(proxy: Proxy) -> None:
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, stream=BrokenStream(b"{")))
    response = proxy.client.post(
        "/local/srv/v1/messages", json=messages_body(stream=False), headers=AUTH
    )
    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "The local model server stopped answering: connection reset"
    )


def test_a_non_streaming_error_reply_is_an_api_error(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(200, json={"error": {"message": "model crashed"}})
    )
    response = proxy.client.post(
        "/local/srv/v1/messages", json=messages_body(stream=False), headers=AUTH
    )
    assert response.status_code == 502
    assert response.json() == {
        "type": "error",
        "error": {"type": "api_error", "message": "model crashed"},
    }


@pytest.mark.parametrize(("status", "kind"), [(400, "invalid_request_error"), (500, "api_error")])
def test_upstream_errors_keep_their_status(proxy: Proxy, status: int, kind: str) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(status, json={"error": {"message": "context too long"}})
    )
    response = proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)
    assert response.status_code == status
    assert response.json() == {
        "type": "error",
        "error": {"type": kind, "message": "context too long"},
    }


def test_an_unreachable_server_fails_at_once_without_a_retry(proxy: Proxy) -> None:
    # The engines retry a 5xx for minutes (live: 145 s); a 424 they do not retry, and the
    # daemon then names the stopped server itself.
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    proxy.upstream.replies.append(refuse)
    response = proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)
    assert response.status_code == 424
    assert response.json() == {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": f"The local model server at {BASE} is not reachable: refused",
        },
    }


def test_an_unknown_server_is_not_found(proxy: Proxy) -> None:
    response = proxy.client.post("/local/gone/v1/messages", json=messages_body(), headers=AUTH)
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "not_found_error"
    assert proxy.upstream.requests == []


def test_a_stream_cut_off_midway_ends_with_an_error_event(proxy: Proxy) -> None:
    first = sse(delta({"content": "Hal"}))[: -len(b"data: [DONE]\n\n")]
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, stream=BrokenStream(first)))
    response = proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)
    found = events(response.text)
    assert [name for name, _ in found][-1] == "error"
    assert found[-1][1]["error"] == {
        "type": "api_error",
        "message": "The local model server stopped answering: connection reset",
    }


def test_an_error_chunk_stops_reading(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        streamed(delta({"content": "a"}), {"error": {"message": "oom"}}, delta({"content": "b"}))
    )
    response = proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)
    found = events(response.text)
    assert [name for name, _ in found] == [
        "message_start",
        "content_block_start",
        "content_block_delta",
        "error",
    ]


def test_count_tokens_is_not_offered(proxy: Proxy) -> None:
    response = proxy.client.post(
        "/local/srv/v1/messages/count_tokens", json=messages_body(), headers=AUTH
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "not_found_error"


def test_a_body_that_is_not_a_json_object_is_refused(proxy: Proxy) -> None:
    response = proxy.client.post("/local/srv/v1/messages", content=b"[1]", headers=AUTH)
    assert response.status_code == 400
    assert response.json()["error"]["type"] == "invalid_request_error"
    responses = proxy.client.post("/local/srv/v1/responses", content=b"nope", headers=AUTH)
    assert responses.status_code == 400
    assert responses.json()["error"]["type"] == "invalid_request_error"


@pytest.mark.parametrize("method", ["HEAD", "GET"])
def test_health_answers_on_any_path(proxy: Proxy, method: str) -> None:
    assert proxy.client.request(method, "/local/srv/api/hello").status_code == 200
    assert proxy.client.request(method, "/local/srv").status_code == 200


def test_other_machines_are_refused() -> None:
    proxy = make_proxy(peer=("192.168.1.30", 4000))
    assert proxy.client.post("/local/srv/v1/messages", json={}, headers=AUTH).status_code == 403
    assert proxy.client.post("/local/srv/v1/responses", json={}, headers=AUTH).status_code == 403
    assert proxy.client.head("/local/srv/api/hello").status_code == 403


def test_a_peer_that_is_a_name_and_not_an_address_is_refused() -> None:
    proxy = make_proxy(peer=("testclient", 50000))
    assert proxy.client.post("/local/srv/v1/messages", json={}, headers=AUTH).status_code == 403


def test_requests_forwarded_from_the_tailnet_are_refused(proxy: Proxy) -> None:
    headers = {**AUTH, "x-forwarded-for": "100.64.0.2"}
    assert proxy.client.post("/local/srv/v1/messages", json={}, headers=headers).status_code == 403


def test_a_missing_or_wrong_key_is_refused(proxy: Proxy) -> None:
    assert proxy.client.post("/local/srv/v1/messages", json={}).status_code == 401
    wrong = proxy.client.post("/local/srv/v1/messages", json={}, headers={"x-api-key": "nope"})
    assert wrong.status_code == 401
    basic = proxy.client.post(
        "/local/srv/v1/responses", json={}, headers={"authorization": f"Basic {KEY}"}
    )
    assert basic.status_code == 401


def test_a_bearer_key_from_ipv6_loopback_is_accepted() -> None:
    proxy = make_proxy(peer=("::1", 4000))
    proxy.upstream.replies.append(streamed(delta({"content": "x"})))
    response = proxy.client.post(
        "/local/srv/v1/messages",
        json=messages_body(),
        headers={"authorization": f"Bearer {KEY}"},
    )
    assert response.status_code == 200


def test_a_request_without_a_peer_is_not_local() -> None:
    assert not local_proxy.is_local(Request({"type": "http", "headers": []}))


def test_an_unconfigured_translator_is_unavailable() -> None:
    proxy = make_proxy(configure=False)
    response = proxy.client.post("/local/srv/v1/messages", json={}, headers=AUTH)
    assert response.status_code == 503


def responses_body(**extra: object) -> JsonObject:
    body: JsonObject = {
        "model": "gpt-oss",
        "instructions": "You are Codex.",
        "stream": True,
        "store": False,
        "input": [
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "hi"}]}
        ],
        "tools": [
            {"type": "function", "name": "exec_command", "parameters": {"type": "object"}},
            {"type": "custom", "name": "apply_patch", "description": "Patch."},
        ],
    }
    body.update(json.loads(json.dumps(extra)))
    return body


def frames(text: str) -> list[JsonObject]:
    return [data for _, data in events(text)]


def test_a_streamed_text_reply_comes_back_as_responses_events(proxy: Proxy) -> None:
    proxy.upstream.replies.append(streamed(delta({"content": "Hello"}), delta({}, "stop"), USAGE))
    response = proxy.client.post("/local/srv/v1/responses", json=responses_body(), headers=AUTH)
    assert response.status_code == 200
    found = frames(response.text)
    assert found[0]["type"] == "response.created"
    assert found[-1]["type"] == "response.completed"
    completed = found[-1]["response"]
    assert isinstance(completed, dict)
    assert completed["usage"] == {
        "input_tokens": 1500,
        "input_tokens_details": {"cached_tokens": 0},
        "output_tokens": 10,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 1510,
    }
    sent = proxy.upstream.body()
    assert sent["messages"] == [
        {"role": "system", "content": "You are Codex."},
        {"role": "user", "content": "hi"},
    ]
    assert sent["stream_options"] == {"include_usage": True}


def test_a_function_call_round_trip(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        streamed(
            delta({"tool_calls": [call(0, "call_1", "exec_command", '{"cmd": "ls"}')]}),
            delta({}, "tool_calls"),
        )
    )
    first = frames(
        proxy.client.post("/local/srv/v1/responses", json=responses_body(), headers=AUTH).text
    )
    done = [obj(frame["item"]) for frame in first if frame["type"] == "response.output_item.done"]
    assert done == [
        {
            "type": "function_call",
            "id": done[0]["id"],
            "call_id": "call_1",
            "name": "exec_command",
            "arguments": '{"cmd": "ls"}',
            "status": "completed",
        }
    ]

    proxy.upstream.replies.append(streamed(delta({"content": "a.txt"}), delta({}, "stop")))
    follow_up = responses_body(
        input=[
            {"type": "message", "role": "user", "content": "list"},
            {
                "type": "function_call",
                "call_id": "call_1",
                "name": "exec_command",
                "arguments": '{"cmd": "ls"}',
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "a.txt"},
        ]
    )
    proxy.client.post("/local/srv/v1/responses", json=follow_up, headers=AUTH)
    sent = proxy.upstream.body()["messages"]
    assert isinstance(sent, list)
    assert sent[-1] == {"role": "tool", "tool_call_id": "call_1", "content": "a.txt"}


def test_apply_patch_comes_back_as_a_custom_tool_call(proxy: Proxy) -> None:
    arguments = json.dumps({"input": "*** Begin Patch\n*** End Patch\n"})
    proxy.upstream.replies.append(
        streamed(
            delta({"tool_calls": [call(0, "call_p", "apply_patch", arguments)]}),
            delta({}, "tool_calls"),
        )
    )
    found = frames(
        proxy.client.post("/local/srv/v1/responses", json=responses_body(), headers=AUTH).text
    )
    done = [frame["item"] for frame in found if frame["type"] == "response.output_item.done"]
    assert len(done) == 1
    item = done[0]
    assert isinstance(item, dict)
    assert item["type"] == "custom_tool_call"
    assert item["input"] == "*** Begin Patch\n*** End Patch\n"


def test_a_non_streaming_response(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": "Hi"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            },
        )
    )
    response = proxy.client.post(
        "/local/srv/v1/responses", json=responses_body(stream=False), headers=AUTH
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["output"][0]["content"] == [
        {"type": "output_text", "text": "Hi", "annotations": []}
    ]


def test_responses_upstream_errors_use_the_openai_shape(proxy: Proxy) -> None:
    proxy.upstream.replies.append(lambda _request: httpx.Response(422, json={"detail": "bad"}))
    response = proxy.client.post("/local/srv/v1/responses", json=responses_body(), headers=AUTH)
    assert response.status_code == 422
    assert response.json() == {
        "error": {"message": "bad", "type": "invalid_request_error", "code": None}
    }


def test_responses_unknown_server_and_unreachable_server(proxy: Proxy) -> None:
    gone = proxy.client.post("/local/gone/v1/responses", json=responses_body(), headers=AUTH)
    assert gone.status_code == 404

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    proxy.upstream.replies.append(refuse)
    down = proxy.client.post("/local/srv/v1/responses", json=responses_body(), headers=AUTH)
    assert down.status_code == 424
    assert down.json()["error"]["type"] == "invalid_request_error"


def test_a_responses_stream_cut_off_midway_fails_the_response(proxy: Proxy) -> None:
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, stream=BrokenStream(b"")))
    response = proxy.client.post("/local/srv/v1/responses", json=responses_body(), headers=AUTH)
    assert [frame["type"] for frame in frames(response.text)] == [
        "response.created",
        "response.failed",
    ]


def test_a_non_streaming_responses_error_reply_is_a_server_error(proxy: Proxy) -> None:
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, json={"error": "oom"}))
    response = proxy.client.post(
        "/local/srv/v1/responses", json=responses_body(stream=False), headers=AUTH
    )
    assert response.status_code == 502
    assert response.json()["error"]["message"] == "oom"


NATIVE_EVENTS = (
    b'event: message_start\ndata: {"type":"message_start"}\n\n',
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
)


class Pieces(httpx.AsyncByteStream):
    def __init__(self, *pieces: bytes) -> None:
        self._pieces = pieces

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for piece in self._pieces:
            yield piece


def native_body(**extra: object) -> JsonObject:
    return messages_body(
        messages=[
            {"role": "user", "content": "Write hello.txt"},
            {"role": "system", "content": [{"type": "text", "text": "<system-reminder>"}]},
            {"role": "assistant", "content": "On it."},
        ],
        **extra,
    )


def test_a_native_server_gets_the_request_with_system_messages_as_user_ones(
    proxy: Proxy,
) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(
            200,
            stream=Pieces(*NATIVE_EVENTS),
            headers={"content-type": "text/event-stream; charset=utf-8"},
        )
    )
    response = proxy.client.post(
        "/local/native/v1/messages?beta=true",
        json=native_body(),
        headers={**AUTH, "anthropic-version": "2023-06-01", "anthropic-beta": "a,b"},
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/event-stream; charset=utf-8"
    assert response.content == b"".join(NATIVE_EVENTS)
    request = proxy.upstream.requests[0]
    assert str(request.url) == f"{BASE}/v1/messages?beta=true"
    assert request.headers["authorization"] == "Bearer server-key"
    assert request.headers["x-api-key"] == "server-key"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert request.headers["anthropic-beta"] == "a,b"
    expected = native_body()
    expected["messages"] = [
        {"role": "user", "content": "Write hello.txt"},
        {"role": "user", "content": [{"type": "text", "text": "<system-reminder>"}]},
        {"role": "assistant", "content": "On it."},
    ]
    assert proxy.upstream.body() == expected


def test_a_native_server_without_a_key_gets_the_placeholder() -> None:
    proxy = make_proxy(upstream_key=None)
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, json={"id": "msg"}))
    proxy.client.post("/local/native/v1/messages", json=native_body(stream=False), headers=AUTH)
    request = proxy.upstream.requests[0]
    assert str(request.url) == f"{BASE}/v1/messages"
    assert request.headers["authorization"] == f"Bearer {PLACEHOLDER_KEY}"
    assert request.headers["x-api-key"] == PLACEHOLDER_KEY
    assert "anthropic-version" not in request.headers


def test_a_native_non_streaming_reply_is_relayed_as_it_is(proxy: Proxy) -> None:
    message = {"id": "msg_1", "type": "message", "content": [{"type": "text", "text": "Hi"}]}
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, json=message))
    response = proxy.client.post(
        "/local/native/v1/messages", json=native_body(stream=False), headers=AUTH
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == message


@pytest.mark.parametrize("stream", [True, False])
def test_native_errors_keep_their_status_and_body(proxy: Proxy, stream: bool) -> None:
    error = {"type": "error", "error": {"type": "invalid_request_error", "message": "too long"}}
    proxy.upstream.replies.append(lambda _request: httpx.Response(400, json=error))
    response = proxy.client.post(
        "/local/native/v1/messages", json=native_body(stream=stream), headers=AUTH
    )
    assert response.status_code == 400
    assert response.json() == error


def test_a_native_reply_without_a_content_type_is_relayed_without_one(proxy: Proxy) -> None:
    proxy.upstream.replies.append(lambda _request: httpx.Response(500, content=b"boom"))
    response = proxy.client.post(
        "/local/native/v1/messages", json=native_body(stream=False), headers=AUTH
    )
    assert response.status_code == 500
    assert response.content == b"boom"
    assert "content-type" not in response.headers


def test_a_server_that_takes_too_long_to_answer_is_a_bad_gateway(proxy: Proxy) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    proxy.upstream.replies.append(slow)
    response = proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)
    assert response.status_code == 502


def test_an_unreachable_native_server_fails_at_once_without_a_retry(proxy: Proxy) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    proxy.upstream.replies.append(refuse)
    response = proxy.client.post("/local/native/v1/messages", json=native_body(), headers=AUTH)
    assert response.status_code == 424
    assert response.json() == {
        "type": "error",
        "error": {
            "type": "invalid_request_error",
            "message": f"The local model server at {BASE} is not reachable: refused",
        },
    }


def test_a_native_stream_cut_off_midway_ends_with_an_error_event(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(
            200,
            stream=BrokenStream(NATIVE_EVENTS[0]),
            headers={"content-type": "text/event-stream"},
        )
    )
    response = proxy.client.post("/local/native/v1/messages", json=native_body(), headers=AUTH)
    found = events(response.text)
    assert [name for name, _ in found] == ["message_start", "error"]
    assert found[-1][1]["error"] == {
        "type": "api_error",
        "message": "The local model server stopped answering: connection reset",
    }


def test_a_native_non_streaming_reply_cut_off_midway_is_a_bad_gateway(proxy: Proxy) -> None:
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, stream=BrokenStream(b"{")))
    response = proxy.client.post(
        "/local/native/v1/messages", json=native_body(stream=False), headers=AUTH
    )
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "api_error"


def test_responses_on_a_native_server_are_still_translated(proxy: Proxy) -> None:
    proxy.upstream.replies.append(streamed(delta({"content": "Hi"}), delta({}, "stop")))
    response = proxy.client.post("/local/native/v1/responses", json=responses_body(), headers=AUTH)
    assert response.status_code == 200
    assert str(proxy.upstream.requests[0].url) == CHAT_URL


CACHED_USAGE: JsonObject = {"input_tokens": 1678, "cache_read_input_tokens": 1536}
CACHED_START = (
    b"event: message_start\ndata: "
    + json.dumps({"type": "message_start", "message": {"usage": CACHED_USAGE}}).encode()
    + b"\n\n"
)
CACHED_DELTA = (
    b"event: message_delta\ndata: "
    + json.dumps({"type": "message_delta", "usage": {**CACHED_USAGE, "output_tokens": 3}}).encode()
    + b"\n\n"
)


def cached_stream(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        stream=Pieces(
            CACHED_START[:20],
            CACHED_START[20:],
            NATIVE_EVENTS[1][:4],
            NATIVE_EVENTS[1][4:],
            CACHED_DELTA,
        ),
        headers={"content-type": "text/event-stream"},
    )


def test_lm_studio_stream_usage_leaves_cache_reads_out_of_input_tokens(proxy: Proxy) -> None:
    proxy.upstream.replies.append(cached_stream)
    response = proxy.client.post("/local/lms/v1/messages", json=native_body(), headers=AUTH)
    found = events(response.text)
    assert [name for name, _ in found] == ["message_start", "message_stop", "message_delta"]
    assert obj(found[0][1]["message"])["usage"] == {
        "input_tokens": 142,
        "cache_read_input_tokens": 1536,
    }
    assert found[2][1]["usage"] == {
        "input_tokens": 142,
        "cache_read_input_tokens": 1536,
        "output_tokens": 3,
    }


def test_lm_studio_whole_reply_usage_leaves_cache_reads_out_of_input_tokens(
    proxy: Proxy,
) -> None:
    message = {"id": "msg_1", "usage": CACHED_USAGE}
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, json=message))
    response = proxy.client.post(
        "/local/lms/v1/messages", json=native_body(stream=False), headers=AUTH
    )
    assert response.status_code == 200
    assert response.json() == {
        "id": "msg_1",
        "usage": {"input_tokens": 142, "cache_read_input_tokens": 1536},
    }


def test_other_native_servers_keep_their_usage_byte_for_byte(proxy: Proxy) -> None:
    proxy.upstream.replies.append(cached_stream)
    streamed_reply = proxy.client.post(
        "/local/native/v1/messages", json=native_body(), headers=AUTH
    )
    assert streamed_reply.content == CACHED_START + NATIVE_EVENTS[1] + CACHED_DELTA
    whole = json.dumps({"usage": CACHED_USAGE}).encode()
    proxy.upstream.replies.append(lambda _request: httpx.Response(200, content=whole))
    reply = proxy.client.post(
        "/local/native/v1/messages", json=native_body(stream=False), headers=AUTH
    )
    assert reply.content == whole


LMS_CONTEXT_ERROR = (
    "The number of tokens to keep from the initial prompt is greater than the context length"
    " (n_keep: 19812 >= n_ctx: 8192). Try to load the model with a larger context length."
)
TOO_FEW = (
    "qwen3-coder is loaded with 8k tokens of context, too few for an agent: it needs 64k."
    " Reload it with more context in LM Studio."
)


@pytest.mark.parametrize("stream", [True, False])
def test_a_context_too_small_for_the_prompt_says_how_to_fix_it(proxy: Proxy, stream: bool) -> None:
    """B106, live: LM Studio loads a model with its own default context on first use."""
    error = {"error": {"message": LMS_CONTEXT_ERROR}}
    proxy.upstream.replies.append(lambda _request: httpx.Response(400, json=error))

    response = proxy.client.post(
        "/local/lms/v1/messages", json=native_body(stream=stream), headers=AUTH
    )

    # 400 is not retried by Claude Code.
    assert response.status_code == 400
    assert response.json() == {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": TOO_FEW},
    }
    assert "prompt is too long" not in response.text


@pytest.mark.parametrize(
    "message",
    [
        "the request exceeds the available context size, try increasing it",
        "Prompt exceeds the model's Context Window",
        "input is longer than the context length",
    ],
)
def test_other_servers_context_errors_are_explained_too(proxy: Proxy, message: str) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(400, json={"error": {"message": message}})
    )

    response = proxy.client.post("/local/srv/v1/messages", json=messages_body(), headers=AUTH)

    assert response.status_code == 400
    assert response.json()["error"]["message"] == (
        "qwen3-coder is loaded with too little context for an agent: it needs 64k."
        " Reload it with more context in its server."
    )


def test_a_responses_request_gets_the_same_explanation(proxy: Proxy) -> None:
    proxy.upstream.replies.append(
        lambda _request: httpx.Response(
            413, json={"error": {"message": "exceeds the available context size"}}
        )
    )

    response = proxy.client.post(
        "/local/lms/v1/responses",
        json={"model": "org/qwen3-coder", "input": "hi", "stream": False},
        headers=AUTH,
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == TOO_FEW
    assert response.json()["error"]["type"] == "invalid_request_error"
