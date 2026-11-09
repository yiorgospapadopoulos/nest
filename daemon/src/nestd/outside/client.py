"""What the `nest` command and `nest mcp` talk to the daemon with (B151): the token from
the daemon's socket, then `/api/outside` over HTTP. Never starts the daemon or opens its
database: it is a thin client (D180)."""

import asyncio
import os
import socket
import time
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TypeVar

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from nestd.config.errors import ConfigError
from nestd.config.loader import load_settings
from nestd.config.models import ServerSettings
from nestd.outside.models import (
    LABELS,
    Chat,
    ChatDetails,
    ClientKind,
    PixieEntry,
    Project,
    StartChat,
    Status,
    TokenAnswer,
    Transcript,
)
from nestd.paths import AppPaths
from nestd.platform import current_platform

# States in which a chat is still at work; WAITING is not one: it waits on the user.
BUSY = ("starting", "running")
POLL_SECONDS = 2.0
# A chat that is idle right after a message may not have begun its turn yet.
START_GRACE_SECONDS = 10.0
SOCKET_SECONDS = 5.0
HTTP_SECONDS = 30.0

M = TypeVar("M", bound=BaseModel)
# Gives a client kind's token; the daemon's socket, or a stand-in in tests.
type TokenSource = Callable[[ClientKind], Awaitable[str]]


class NestUnavailableError(Exception):
    """The daemon is not running, or this client may not use it; the message says why."""


class InsideNestError(NestUnavailableError):
    """The asker runs inside a Nest chat, which has its own Nest tools."""


class NestApiError(Exception):
    """The daemon refused or failed a request; the message is its own."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status


def default_paths(env: Mapping[str, str] = os.environ) -> AppPaths:
    return AppPaths.from_env(env, Path.home(), current_platform())


def daemon_url(paths: AppPaths) -> str:
    try:
        port = load_settings(paths).server.port
    except ConfigError:
        port = ServerSettings().port
    return f"http://127.0.0.1:{port}"


def ask_token(path: Path, kind: ClientKind) -> str:
    """The daemon's answer for `kind` from its socket at `path`."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(SOCKET_SECONDS)
            sock.connect(str(path))
            sock.sendall(kind.encode() + b"\n")
            sock.shutdown(socket.SHUT_WR)
            data = b""
            while chunk := sock.recv(4096):
                data += chunk
    except (FileNotFoundError, ConnectionRefusedError):
        msg = "Nest is not running. Open the Nest app, or run `nest doctor` to see why."
        raise NestUnavailableError(msg) from None
    except OSError as error:
        raise NestUnavailableError(f"Could not reach Nest: {error}") from error
    try:
        answer = TokenAnswer.model_validate_json(data)
    except ValidationError:
        raise NestUnavailableError("Nest did not answer as expected. Is it up to date?") from None
    if answer.token is not None:
        return answer.token
    if answer.error == "inside_nest":
        raise InsideNestError(_refusal(answer, kind))
    raise NestUnavailableError(_refusal(answer, kind))


def _refusal(answer: TokenAnswer, kind: ClientKind) -> str:
    if answer.error == "inside_nest":
        return (
            "This runs inside a Nest chat, which uses its own Nest tools instead, or detached"
            " from any terminal or app. Run it in your own terminal."
        )
    if answer.error == "off":
        return (
            f"{LABELS[kind]} is switched off in Nest. Switch it on in Nest: Settings >"
            " Terminal agents."
        )
    return "Nest does not know this client. Is Nest up to date?"


class NestClient:
    def __init__(
        self,
        kind: ClientKind,
        paths: AppPaths | None = None,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        token_source: TokenSource | None = None,
    ) -> None:
        """`transport` and `token_source` replace the network and the socket in tests."""
        self.kind: ClientKind = kind
        self.paths = paths or default_paths()
        self.base_url = daemon_url(self.paths)
        self._transport = transport
        self._token_source = token_source
        self._token: str | None = None

    # Read

    async def status(self) -> Status:
        return await self._get(Status, "/status")

    async def projects(self) -> list[Project]:
        return await self._get_list(Project, "/projects")

    async def chats(self, project: str | None = None, state: str | None = None) -> list[Chat]:
        params = {k: v for k, v in (("project", project), ("state", state)) if v is not None}
        return await self._get_list(Chat, "/chats", params)

    async def chat(self, chat_id: str) -> ChatDetails:
        return await self._get(ChatDetails, f"/chats/{chat_id}")

    async def transcript(
        self, chat_id: str, since: int | None = None, limit: int | None = None
    ) -> Transcript:
        params = {k: str(v) for k, v in (("since", since), ("limit", limit)) if v is not None}
        return await self._get(Transcript, f"/chats/{chat_id}/transcript", params)

    async def pixies(self) -> list[PixieEntry]:
        return await self._get_list(PixieEntry, "/pixies")

    async def resolve(self, chat: str) -> str:
        """A chat's id from its id or the start of it, as `nest list` shows them."""
        found = [c.id for c in await self.chats() if c.id.startswith(chat)]
        if chat in found:
            return chat
        if len(found) == 1:
            return found[0]
        if not found:
            raise NestApiError(404, f"No chat's id starts with {chat}.")
        raise NestApiError(409, f"{len(found)} chats' ids start with {chat}; give more of it.")

    # Act

    async def start(self, request: StartChat) -> ChatDetails:
        body = request.model_dump(mode="json", exclude_none=True)
        return await self._send(ChatDetails, "POST", "/chats", body)

    async def send(self, chat_id: str, text: str) -> ChatDetails:
        return await self._send(ChatDetails, "POST", f"/chats/{chat_id}/messages", {"text": text})

    async def call(self, handle: str, project: str, task: str) -> ChatDetails:
        body = {"project": project, "task": task}
        return await self._send(ChatDetails, "POST", f"/pixies/{handle.lstrip('@')}/call", body)

    async def connect(self) -> None:
        """Gets a token now, so a client that may not use Nest learns it at once."""
        await self._current_token(fresh=False)

    async def wait(self, sent: ChatDetails, seconds: float) -> ChatDetails:
        """The chat once it stops working on what was just sent (`sent` is the chat as
        the start or the message left it), or as it is after `seconds`."""
        started = time.monotonic()
        chat = sent
        while True:
            elapsed = time.monotonic() - started
            # A turn that has not begun yet leaves the chat as it was.
            unchanged = chat.updated_at <= sent.updated_at and elapsed < START_GRACE_SECONDS
            if (chat.state not in BUSY and not unchanged) or elapsed >= seconds:
                return chat
            await asyncio.sleep(min(POLL_SECONDS, max(0.0, seconds - elapsed)))
            chat = await self.chat(sent.id)

    # Inside

    async def _get(self, model: type[M], path: str, params: Mapping[str, str] | None = None) -> M:
        response = await self._request("GET", path, params=params)
        return model.model_validate_json(response.content)

    async def _get_list(
        self, model: type[M], path: str, params: Mapping[str, str] | None = None
    ) -> list[M]:
        response = await self._request("GET", path, params=params)
        return TypeAdapter(list[model]).validate_json(response.content)

    async def _send(self, model: type[M], method: str, path: str, body: object) -> M:
        response = await self._request(method, path, json=body)
        return model.model_validate_json(response.content)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: object = None,
    ) -> httpx.Response:
        for attempt in range(2):
            token = await self._current_token(fresh=attempt > 0)
            try:
                async with httpx.AsyncClient(
                    base_url=self.base_url + "/api/outside",
                    transport=self._transport,
                    timeout=HTTP_SECONDS,
                ) as http:
                    response = await http.request(
                        method,
                        path,
                        params=params,
                        json=json,
                        headers={"Authorization": f"Bearer {token}"},
                    )
            except httpx.TransportError as error:
                msg = f"Could not reach Nest at {self.base_url}: {error}"
                raise NestUnavailableError(msg) from error
            # A restart or switching the client off drops its token: ask once for another.
            if response.status_code == 401 and attempt == 0:
                continue
            if response.is_error:
                raise NestApiError(response.status_code, _detail(response))
            return response
        raise NestApiError(401, "Nest did not accept this client's token.")

    async def _current_token(self, *, fresh: bool) -> str:
        if self._token is None or fresh:
            source = self._token_source or self._ask_socket
            self._token = await source(self.kind)
        return self._token

    async def _ask_socket(self, kind: ClientKind) -> str:
        path = self.paths.outside_socket
        if path is None:
            raise NestUnavailableError("Nest's data folder has no socket.")
        return await asyncio.to_thread(ask_token, path, kind)


class _Problem(BaseModel):
    loc: list[str | int] = []
    msg: str = ""


class _ErrorBody(BaseModel):
    # A message, or FastAPI's list of validation problems.
    detail: str | list[_Problem] | None = None


def _detail(response: httpx.Response) -> str:
    try:
        detail = _ErrorBody.model_validate_json(response.content).detail
    except ValidationError:
        return response.text or f"Nest answered {response.status_code}"
    if isinstance(detail, str):
        return detail
    if detail:
        where = ".".join(str(part) for part in detail[0].loc[1:])
        return f"{where}: {detail[0].msg}" if where else detail[0].msg
    return f"Nest answered {response.status_code}"
