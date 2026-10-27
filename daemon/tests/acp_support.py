"""A recorded ACP engine in memory, so ACP tests never start a real engine (B107).

The fixtures under `fixtures/acp/` are live transcripts from the B107 spike (paths made
neutral, the user's skills left out), one JSON per line: `{"dir": "out"|"in", "msg": ...}`,
`out` being the client's. The fake agent answers each request of the client with what the
engine did after the same request in the transcript: its notifications, its own requests
(waiting for the client's answer to each) and its answer. A transcript's later exchanges
of a method come in order, and the last one repeats.
"""

import asyncio
import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from nestd.providers.acp_process import AcpLaunch
from nestd.providers.acp_rpc import JsonObject

FIXTURES = Path(__file__).parent / "fixtures" / "acp"
# The folder the fixtures' sessions ran in; replaced by the test's.
RECORDED_CWD = "/work/repo"


@dataclass(frozen=True)
class Step:
    # push: a notification; ask: a request of the agent, answered before the next step;
    # expect: wait for the client's notification `msg["method"]`; answer: the answer.
    action: Literal["push", "ask", "expect", "answer"]
    msg: JsonObject


def load(
    name: str, cwd: Path, replace: dict[str, str] | None = None
) -> list[tuple[str, JsonObject]]:
    entries: list[tuple[str, JsonObject]] = []
    for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines():
        line = line.replace(RECORDED_CWD, str(cwd))
        for old, new in (replace or {}).items():
            line = line.replace(old, new)
        entry = json.loads(line)
        entries.append((entry["dir"], cast("JsonObject", entry["msg"])))
    return entries


def exchanges(entries: list[tuple[str, JsonObject]]) -> dict[str, deque[list[Step]]]:
    """Each client request's steps, by method, in the transcript's order."""
    found: dict[str, deque[list[Step]]] = {}
    index = 0
    while index < len(entries):
        direction, msg = entries[index]
        index += 1
        method = msg.get("method")
        if direction != "out" or not isinstance(method, str) or "id" not in msg:
            continue
        steps: list[Step] = []
        while index < len(entries):
            way, reply = entries[index]
            index += 1
            if way == "out":
                if "id" not in reply and isinstance(reply.get("method"), str):
                    steps.append(Step("expect", reply))
                continue  # the client's answer to an agent request: the client makes its own
            if reply.get("id") == msg["id"] and "method" not in reply:
                steps.append(Step("answer", reply))
                break
            steps.append(Step("ask" if "id" in reply else "push", reply))
        found.setdefault(method, deque()).append(steps)
    return found


class FakeTransport:
    def __init__(self, agent: "FakeAgent", launch: AcpLaunch, cwd: Path) -> None:
        self.agent = agent
        self.launch = launch
        self.cwd = cwd
        self.closed = False
        self._out: asyncio.Queue[bytes] = asyncio.Queue()

    async def write(self, line: bytes) -> None:
        if self.closed:
            msg = "the fake engine was closed"
            raise BrokenPipeError(msg)
        self.agent.receive(self, cast("JsonObject", json.loads(line)))

    async def readline(self) -> bytes:
        return await self._out.get()

    async def close(self) -> None:
        self.closed = True
        self.end()

    def stderr(self) -> str:
        return ""

    def push(self, message: JsonObject) -> None:
        self._out.put_nowait(json.dumps(message).encode() + b"\n")

    def end(self) -> None:
        self._out.put_nowait(b"")


class FakeAgent:
    """Usable as an `AcpTransportFactory`."""

    def __init__(self, *fixtures: list[tuple[str, JsonObject]]) -> None:
        self.exchanges: dict[str, deque[list[Step]]] = {}
        for entries in fixtures:
            for method, found in exchanges(entries).items():
                self.exchanges.setdefault(method, deque()).extend(found)
        self.transports: list[FakeTransport] = []
        # Every message the client wrote, in order.
        self.sent: list[JsonObject] = []
        # The client's answers to the agent's requests, by the request's method.
        self.answers: list[tuple[str, JsonObject]] = []
        self._waiting: dict[object, asyncio.Future[JsonObject]] = {}
        self._notified: dict[str, asyncio.Event] = {}
        # Steps queued after one another, answered before the transcript's (B112).
        self._queued: dict[str, deque[list[Step]]] = {}
        # The transport of each request, by method, in order (B112).
        self.asked_on: dict[str, list[FakeTransport]] = {}
        self._next_id = 9000
        self._plays: set[asyncio.Task[None]] = set()

    async def __call__(self, launch: AcpLaunch, cwd: Path) -> FakeTransport:
        transport = FakeTransport(self, launch, cwd)
        self.transports.append(transport)
        return transport

    @property
    def transport(self) -> FakeTransport:
        return self.transports[-1]

    def script(self, method: str, steps: list[Step]) -> None:
        """Answer the next request of `method` with these steps first."""
        self.exchanges.setdefault(method, deque()).appendleft(steps)

    def queue(self, method: str, steps: list[Step]) -> None:
        """Answer a later request of `method` with these steps, after those queued before."""
        self._queued.setdefault(method, deque()).append(steps)

    def release(self, name: str) -> None:
        """Let an `expect` step waiting for `name` go on, as if the client had sent it."""
        self._notified.setdefault(name, asyncio.Event()).set()

    async def request(
        self, transport: FakeTransport, method: str, params: JsonObject
    ) -> JsonObject:
        """A request of the agent outside any prompt's steps; the client's whole answer."""
        self._next_id += 1
        waiting: asyncio.Future[JsonObject] = asyncio.get_running_loop().create_future()
        self._waiting[self._next_id] = waiting
        message: JsonObject = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        message["params"] = params
        transport.push(message)
        return await waiting

    def answer_with(self, method: str, result: JsonObject) -> None:
        """Answer every request of `method` with this result."""
        self.exchanges[method] = deque([[Step("answer", {"result": result})]])

    def methods(self) -> list[str]:
        return [m["method"] for m in self.sent if isinstance(m.get("method"), str)]  # pyright: ignore[reportReturnType]

    def requests(self, method: str) -> list[JsonObject]:
        return [cast("JsonObject", m["params"]) for m in self.sent if m.get("method") == method]

    def answered(self, method: str) -> list[JsonObject]:
        return [answer for asked, answer in self.answers if asked == method]

    def receive(self, transport: FakeTransport, message: JsonObject) -> None:
        self.sent.append(message)
        method = message.get("method")
        request_id = message.get("id")
        if not isinstance(method, str):
            waiting = self._waiting.pop(request_id, None)
            if waiting is not None:
                waiting.set_result(message)
            return
        if request_id is None:
            self._notified.setdefault(method, asyncio.Event()).set()
            return
        self.asked_on.setdefault(method, []).append(transport)
        queued = self._queued.get(method)
        if queued:
            self._start(transport, request_id, queued.popleft())
            return
        found = self.exchanges.get(method)
        if not found:
            transport.push({"jsonrpc": "2.0", "id": request_id, "result": {}})
            return
        steps = found.popleft() if len(found) > 1 else found[0]
        self._start(transport, request_id, steps)

    def _start(self, transport: FakeTransport, request_id: object, steps: list[Step]) -> None:
        task = asyncio.create_task(self._play(transport, request_id, steps))
        self._plays.add(task)
        task.add_done_callback(self._plays.discard)

    async def _play(self, transport: FakeTransport, request_id: object, steps: list[Step]) -> None:
        for step in steps:
            if transport.closed:
                return
            if step.action == "push":
                transport.push(step.msg)
            elif step.action == "expect":
                method = str(step.msg["method"])
                await self._notified.setdefault(method, asyncio.Event()).wait()
            elif step.action == "ask":
                waiting = asyncio.get_running_loop().create_future()
                self._waiting[step.msg["id"]] = waiting
                transport.push(step.msg)
                reply = await waiting
                self.answers.append((str(step.msg["method"]), reply))
            else:
                transport.push({**step.msg, "jsonrpc": "2.0", "id": request_id})  # pyright: ignore[reportArgumentType]
