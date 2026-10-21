"""A scripted `codex app-server` in memory, so Codex tests never start the real binary."""

import asyncio
import json
from collections import deque
from collections.abc import Awaitable, Callable
from typing import cast

from pydantic import JsonValue

from nestd.providers.codex_process import CodexLaunch
from nestd.providers.codex_rpc import JsonObject

type Answer = JsonObject | Callable[[JsonObject], JsonObject]

SIGNED_IN: JsonObject = {
    "account": {"type": "chatgpt", "email": "me@example.com", "planType": "plus"},
    "requiresOpenaiAuth": True,
}
SIGNED_OUT: JsonObject = {"account": None, "requiresOpenaiAuth": True}

# `account/rateLimits/read` for a plan with a five-hour and a weekly window.
RATE_LIMITS: JsonObject = {
    "rateLimits": {
        "limitId": "codex",
        "primary": {"usedPercent": 30, "windowDurationMins": 300, "resetsAt": 1767283200},
        "secondary": {"usedPercent": 81.5, "windowDurationMins": 10080, "resetsAt": None},
        "planType": "plus",
    },
    "rateLimitsByLimitId": None,
}

MODELS: JsonObject = {
    "data": [
        {
            "id": "gpt-6.1-sol",
            "model": "gpt-6.1-sol",
            "displayName": "GPT-6.1 Sol",
            "description": "Default model",
            "hidden": False,
            "isDefault": True,
            "supportedReasoningEfforts": [
                {"reasoningEffort": "low", "description": "Fast"},
                {"reasoningEffort": "high", "description": "Deep"},
                {"reasoningEffort": "ultra", "description": "Deepest"},
            ],
            "defaultReasoningEffort": "low",
        },
        {
            "id": "gpt-5.5",
            "model": "gpt-5.5",
            "displayName": "GPT-5.5",
            "description": "Older",
            "hidden": False,
            "isDefault": False,
            "supportedReasoningEfforts": [],
            "defaultReasoningEffort": "medium",
        },
        {
            "id": "secret",
            "model": "secret",
            "displayName": "Hidden",
            "description": "",
            "hidden": True,
            "isDefault": False,
            "supportedReasoningEfforts": [],
            "defaultReasoningEffort": "medium",
        },
    ],
    "nextCursor": None,
}


def default_answers() -> dict[str, Answer]:
    return {
        "initialize": {"userAgent": "nest/0.1", "codexHome": "/codex-home"},
        "account/read": SIGNED_IN,
        "account/rateLimits/read": RATE_LIMITS,
        "model/list": MODELS,
        "thread/start": {"thread": {"id": "thread-1"}, "model": "gpt-6.1-sol"},
        "thread/resume": lambda params: {"thread": {"id": params["threadId"]}},
        "turn/start": {"turn": {"id": "turn-1", "status": "inProgress"}},
        "turn/steer": {"turnId": "turn-1"},
        "turn/interrupt": {},
        "mcpServerStatus/list": {"data": [], "nextCursor": None},
    }


class FakeTransport:
    def __init__(self, server: "FakeAppServer", launch: CodexLaunch) -> None:
        self.server = server
        self.launch = launch
        self.closed = False
        self._out: asyncio.Queue[bytes] = asyncio.Queue()

    async def write(self, line: bytes) -> None:
        if self.closed:
            msg = "the fake app-server was closed"
            raise BrokenPipeError(msg)
        await self.server.receive(self, cast("JsonObject", json.loads(line)))

    async def readline(self) -> bytes:
        return await self._out.get()

    async def close(self) -> None:
        self.closed = True
        self.end()

    def stderr(self) -> str:
        return self.server.stderr

    def push(self, message: JsonObject) -> None:
        self._out.put_nowait(json.dumps(message).encode() + b"\n")

    def push_raw(self, line: bytes) -> None:
        self._out.put_nowait(line)

    def end(self) -> None:
        self._out.put_nowait(b"")


class FakeAppServer:
    """Answers requests by method; a `turn/start` also pushes the next scripted turn's
    notifications after its answer. Usable as a `TransportFactory`.
    """

    def __init__(self) -> None:
        self.answers = default_answers()
        # Answers for the app-servers started on one Codex home (an account's, B98), by
        # CODEX_HOME; any other method is answered as above.
        self.home_answers: dict[str, dict[str, Answer]] = {}
        self.errors: dict[str, tuple[int, str]] = {}
        # The `data` of an error answer, by method.
        self.error_data: dict[str, JsonValue] = {}
        # Methods left unanswered, like a request the server is still working on.
        self.silent: set[str] = set()
        self.turns: deque[list[JsonObject]] = deque()
        self.steer_turns: deque[list[JsonObject]] = deque()
        self.launches: list[CodexLaunch] = []
        self.transports: list[FakeTransport] = []
        # Every message the client wrote, in order.
        self.sent: list[JsonObject] = []
        self.stderr = ""
        self.spawn_error: Exception | None = None
        self._next_id = 1000
        self._waiting: dict[int, asyncio.Future[JsonObject]] = {}

    async def __call__(self, launch: CodexLaunch) -> FakeTransport:
        if self.spawn_error is not None:
            raise self.spawn_error
        transport = FakeTransport(self, launch)
        self.launches.append(launch)
        self.transports.append(transport)
        return transport

    @property
    def transport(self) -> FakeTransport:
        return self.transports[-1]

    def requests(self, method: str) -> list[JsonObject]:
        return [cast("JsonObject", m["params"]) for m in self.sent if m.get("method") == method]

    def homes(self) -> list[str | None]:
        """The CODEX_HOME of each app-server started, in order."""
        return [launch.env.get("CODEX_HOME") for launch in self.launches]

    def script(self, *notifications: JsonObject) -> None:
        self.turns.append(list(notifications))

    def notify(self, method: str, params: JsonObject) -> None:
        self.transport.push({"method": method, "params": params})

    async def request(self, method: str, params: JsonObject) -> JsonObject:
        """A server request; returns the client's whole answer message."""
        self._next_id += 1
        answer = asyncio.get_running_loop().create_future()
        self._waiting[self._next_id] = answer
        self.transport.push({"id": self._next_id, "method": method, "params": params})
        return await answer

    async def receive(self, transport: FakeTransport, message: JsonObject) -> None:
        self.sent.append(message)
        method = message.get("method")
        request_id = message.get("id")
        if not isinstance(method, str):
            if isinstance(request_id, int) and request_id in self._waiting:
                self._waiting.pop(request_id).set_result(message)
            return
        if request_id is None or method in self.silent:
            return
        if method in self.errors:
            code, text = self.errors[method]
            error: JsonObject = {"code": code, "message": text}
            if method in self.error_data:
                error["data"] = self.error_data[method]
            transport.push({"id": request_id, "error": error})
            return
        home = self.home_answers.get(transport.launch.env.get("CODEX_HOME", ""), {})
        answer = home.get(method, self.answers.get(method, {}))
        params = cast("JsonObject", message.get("params") or {})
        result = answer(params) if callable(answer) else answer
        transport.push({"id": request_id, "result": result})
        if method == "turn/start" and self.turns:
            for notification in self.turns.popleft():
                transport.push(notification)
        if method == "turn/steer" and self.steer_turns:
            for notification in self.steer_turns.popleft():
                transport.push(notification)


def note(method: str, **params: JsonValue) -> JsonObject:
    return {"method": method, "params": dict(params)}


def turn_completed(
    status: str = "completed",
    turn_id: str = "turn-1",
    error: JsonValue = None,
    duration_ms: int | None = 1200,
) -> JsonObject:
    return note(
        "turn/completed",
        threadId="thread-1",
        turn={"id": turn_id, "status": status, "error": error, "durationMs": duration_ms},
    )


def item(phase: str, body: JsonObject, at_ms: int = 0) -> JsonObject:
    stamp = "startedAtMs" if phase == "started" else "completedAtMs"
    return note(f"item/{phase}", item=body, threadId="thread-1", turnId="turn-1", **{stamp: at_ms})


async def answered(waiting: Awaitable[JsonObject]) -> JsonValue:
    """The `result` of a client's answer to a server request."""
    return (await waiting).get("result")
