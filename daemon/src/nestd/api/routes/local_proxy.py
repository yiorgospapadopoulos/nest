"""Nest's proxy for local model servers: Claude Code always points at `/local/{server_id}`,
Codex when the server lacks the Responses API.

Claude Code's Anthropic Messages requests pass through to a server that speaks Messages
itself, with system messages turned into user ones (see `anthropic_native`); for any other
server they are translated to Chat Completions, as Codex's Responses requests always are.

Not under device auth. A request must come from this Mac (loopback, and not forwarded by
`tailscale serve`, which also connects from loopback) and carry the daemon's translator key
as `x-api-key` or `Authorization: Bearer`. The server's own address and key come from the
`resolve` callable given to `configure`, so the agents never see the server key.
"""

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from hmac import compare_digest
from ipaddress import ip_address
from typing import Protocol

import httpx
from fastapi import APIRouter, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import JsonValue, TypeAdapter, ValidationError

from nestd.local.run import PLACEHOLDER_KEY
from nestd.local.translate import anthropic_request, responses_request
from nestd.local.translate.anthropic_native import UsageFix, fixed_reply, native_request
from nestd.local.translate.anthropic_reply import AnthropicReply
from nestd.local.translate.chat_stream import completion_chunk
from nestd.local.translate.errors import anthropic_error, openai_error, upstream_message
from nestd.local.translate.responses_reply import ResponsesReply
from nestd.local.translate.sse import chunks, encode
from nestd.local.translate.upstream import Upstream
from nestd.local.translate.values import JsonObject, string

type Resolve = Callable[[str], Awaitable[Upstream | None]]
type _ErrorBody = Callable[[int, str], JsonObject]

# Reading a long prompt can keep a local server quiet for minutes before its first token.
TIMEOUT = httpx.Timeout(600.0, connect=5.0)
_NOT_AN_OBJECT = "The request body must be a JSON object"
_BODY = TypeAdapter[dict[str, JsonValue]](dict[str, JsonValue])
# Claude Code's headers a native server may read; its auth headers are never passed on.
_ANTHROPIC_HEADERS = ("anthropic-version", "anthropic-beta")
# How servers say a request does not fit the context the model is loaded with: LM Studio
# ("greater than the context length"), llama.cpp ("exceeds the available context size"),
# Ollama and others.
_CONTEXT_WORDS = ("context length", "context window", "context size")

router = APIRouter(prefix="/local/{server_id}", include_in_schema=False)


@dataclass(frozen=True)
class _Settings:
    resolve: Resolve
    key: str
    transport: httpx.AsyncBaseTransport | None


def configure(
    app: FastAPI,
    *,
    resolve: Resolve,
    key: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> None:
    """`resolve(server_id)` gives where the server is and whether it speaks Messages, or
    None for an unknown server; `transport` replaces the network in tests."""
    app.state.local_proxy = _Settings(resolve, key, transport)


class _Reply(Protocol):
    done: bool
    error: str | None

    def start(self) -> bytes: ...
    def feed(self, chunk: JsonObject) -> bytes: ...
    def finish(self) -> bytes: ...
    def fail(self, message: str) -> bytes: ...


@router.api_route("", methods=["GET", "HEAD"])
@router.api_route("/{path:path}", methods=["GET", "HEAD"])
async def health(request: Request) -> Response:
    """Claude Code checks `HEAD /api/hello` before it starts."""
    _require_local(request)
    return Response(status_code=status.HTTP_200_OK)


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> Response:
    """Not offered: Claude Code estimates on its own when this is missing."""
    _authorize(request)
    message = "Counting tokens is not offered for local models"
    return _error(anthropic_error, status.HTTP_404_NOT_FOUND, message)


@router.post("/v1/messages")
async def messages(server_id: str, request: Request) -> Response:
    settings = _authorize(request)
    body = await _body(request)
    if body is None:
        return _error(anthropic_error, status.HTTP_400_BAD_REQUEST, _NOT_AN_OBJECT)
    found = await _resolve(settings, server_id, anthropic_error)
    if isinstance(found, Response):
        return found
    if found.messages:
        return await _pass_through(settings, found, request, body)
    model = string(body.get("model"))
    reply = AnthropicReply(model)
    chat = anthropic_request.chat_request(body)
    return await _translate(settings, found, chat, reply, reply.message, anthropic_error, model)


@router.post("/v1/responses")
async def responses(server_id: str, request: Request) -> Response:
    settings = _authorize(request)
    body = await _body(request)
    if body is None:
        return _error(openai_error, status.HTTP_400_BAD_REQUEST, _NOT_AN_OBJECT)
    found = await _resolve(settings, server_id, openai_error)
    if isinstance(found, Response):
        return found
    model = string(body.get("model"))
    chat = responses_request.chat_request(body)
    reply = ResponsesReply(model, chat.custom_tools, int(time.time()))
    return await _translate(settings, found, chat.body, reply, reply.response, openai_error, model)


def is_local(request: Request) -> bool:
    peer = request.client.host if request.client is not None else None
    if peer is None or "x-forwarded-for" in request.headers:
        return False
    try:
        return ip_address(peer).is_loopback
    except ValueError:
        return False


def _require_local(request: Request) -> None:
    if not is_local(request):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only this Mac can use the translator")


def _authorize(request: Request) -> _Settings:
    _require_local(request)
    settings = getattr(request.app.state, "local_proxy", None)
    if not isinstance(settings, _Settings):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "the translator is not set up")
    scheme, _, credentials = request.headers.get("authorization", "").partition(" ")
    bearer = credentials.strip() if scheme.lower() == "bearer" else ""
    given = request.headers.get("x-api-key") or bearer
    if not compare_digest(given.encode(), settings.key.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong or missing translator key")
    return settings


async def _body(request: Request) -> JsonObject | None:
    try:
        return _BODY.validate_json(await request.body())
    except ValidationError:
        return None


async def _resolve(settings: _Settings, server_id: str, error: _ErrorBody) -> Upstream | Response:
    found = await settings.resolve(server_id)
    if found is None:
        message = f"There is no local model server {server_id}"
        return _error(error, status.HTTP_404_NOT_FOUND, message)
    return found


def _error(body: _ErrorBody, code: int, message: str) -> JSONResponse:
    return JSONResponse(body(code, message), status_code=code)


async def _send(
    settings: _Settings,
    upstream: Upstream,
    path: str,
    body: JsonObject,
    headers: dict[str, str],
    error: _ErrorBody,
) -> tuple[httpx.AsyncClient, httpx.Response] | Response:
    """The server's reply, open for streaming. A server that cannot be reached is a 424,
    which the engines do not retry (they retry a 5xx for minutes); the daemon then names
    the stopped server. Other failures are a 502.
    """
    client = httpx.AsyncClient(transport=settings.transport, timeout=TIMEOUT)
    request = client.build_request(
        "POST", f"{upstream.base_url.rstrip('/')}{path}", json=body, headers=headers
    )
    try:
        return client, await client.send(request, stream=True)
    except httpx.HTTPError as exc:
        await client.aclose()
        message = f"The local model server at {upstream.base_url} is not reachable: {exc}"
        down = isinstance(exc, httpx.ConnectError | httpx.ConnectTimeout)
        code = status.HTTP_424_FAILED_DEPENDENCY if down else status.HTTP_502_BAD_GATEWAY
        return _error(error, code, message)


async def _read(
    client: httpx.AsyncClient, reply: httpx.Response, error: _ErrorBody
) -> bytes | Response:
    try:
        return await reply.aread()
    except httpx.HTTPError as exc:
        return _error(error, status.HTTP_502_BAD_GATEWAY, _stopped(exc))
    finally:
        await reply.aclose()
        await client.aclose()


async def _pass_through(
    settings: _Settings, upstream: Upstream, request: Request, body: JsonObject
) -> Response:
    key = upstream.key or PLACEHOLDER_KEY
    headers = {
        name: request.headers[name] for name in _ANTHROPIC_HEADERS if name in request.headers
    }
    headers.update({"authorization": f"Bearer {key}", "x-api-key": key})
    query = request.url.query
    path = f"/v1/messages?{query}" if query else "/v1/messages"
    opened = await _send(settings, upstream, path, native_request(body), headers, anthropic_error)
    if isinstance(opened, Response):
        return opened
    client, reply = opened
    kept = (
        {"content-type": reply.headers["content-type"]} if "content-type" in reply.headers else {}
    )
    if reply.is_success and body.get("stream") is True:
        fix = UsageFix() if upstream.usage_counts_cache else None
        return StreamingResponse(
            _pass_stream(client, reply, fix), status_code=reply.status_code, headers=kept
        )
    content = await _read(client, reply, anthropic_error)
    if isinstance(content, Response):
        return content
    small = _too_little_context(reply.status_code, content, upstream, string(body.get("model")))
    if small is not None:
        return _error(anthropic_error, status.HTTP_400_BAD_REQUEST, small)
    if upstream.usage_counts_cache and reply.is_success:
        content = fixed_reply(content)
    return Response(content, status_code=reply.status_code, headers=kept)


async def _pass_stream(
    client: httpx.AsyncClient, reply: httpx.Response, fix: UsageFix | None
) -> AsyncIterator[bytes]:
    try:
        async for piece in reply.aiter_bytes():
            yield piece if fix is None else fix.feed(piece)
        if fix is not None:
            yield fix.finish()
    except httpx.HTTPError as exc:
        yield encode("error", anthropic_error(status.HTTP_502_BAD_GATEWAY, _stopped(exc)))
    finally:
        await reply.aclose()
        await client.aclose()


async def _translate(
    settings: _Settings,
    upstream: Upstream,
    chat: JsonObject,
    reply: _Reply,
    whole: Callable[[], JsonObject],
    error: _ErrorBody,
    model: str,
) -> Response:
    headers = {"authorization": f"Bearer {upstream.key}"} if upstream.key else {}
    opened = await _send(settings, upstream, "/v1/chat/completions", chat, headers, error)
    if isinstance(opened, Response):
        return opened
    client, answer = opened
    if answer.is_success and chat.get("stream") is True:
        return StreamingResponse(_relay(client, answer, reply), media_type="text/event-stream")
    content = await _read(client, answer, error)
    if isinstance(content, Response):
        return content
    small = _too_little_context(answer.status_code, content, upstream, model)
    if small is not None:
        return _error(error, status.HTTP_400_BAD_REQUEST, small)
    if not answer.is_success:
        return _error(error, answer.status_code, upstream_message(content))
    try:
        completion = _BODY.validate_json(content)
    except ValidationError:
        message = "The local model server sent a reply that is not JSON"
        return _error(error, status.HTTP_502_BAD_GATEWAY, message)
    reply.feed(completion_chunk(completion))
    if reply.error is not None:
        return _error(error, status.HTTP_502_BAD_GATEWAY, reply.error)
    reply.finish()
    return JSONResponse(whole())


async def _relay(
    client: httpx.AsyncClient, upstream: httpx.Response, reply: _Reply
) -> AsyncIterator[bytes]:
    try:
        yield reply.start()
        try:
            async for chunk in chunks(upstream.aiter_lines()):
                yield reply.feed(chunk)
                if reply.done:
                    return
        except httpx.HTTPError as exc:
            yield reply.fail(_stopped(exc))
            return
        yield reply.finish()
    finally:
        await upstream.aclose()
        await client.aclose()


def _too_little_context(
    status_code: int, content: bytes, upstream: Upstream, model: str
) -> str | None:
    """What to tell the user when the server refused a request for its context: a 400,
    which the engines do not retry, naming how much there is and what is needed (B106).
    """
    if not 400 <= status_code < 500:
        return None
    reason = upstream_message(content).lower()
    if not any(words in reason for words in _CONTEXT_WORDS):
        return None
    context = upstream.contexts.get(model)
    loaded = (
        "is loaded with too little context"
        if context is None
        else f"is loaded with {context // 1024}k tokens of context, too few"
    )
    return (
        f"{model.rsplit('/', 1)[-1]} {loaded} for an agent: it needs 64k."
        f" Reload it with more context in {upstream.app or 'its server'}."
    )


def _stopped(exc: httpx.HTTPError) -> str:
    return f"The local model server stopped answering: {exc}"
