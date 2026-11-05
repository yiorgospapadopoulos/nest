"""B112: a pixie called across engines works like a Claude Code subagent call, on every
engine. Each test runs the same scenario with the called pixie on each engine: Claude
(the scripted provider standing in for the Claude Agent SDK run), Codex (the in-memory
app-server) and an ACP engine (OpenCode, the recorded agent). The caller is on another
engine, so the call always goes through Nest's call_pixie tool.

To add an engine, give `Called` a branch for it (scripting a turn that waits, reports,
asks or hits the usage limit) and add its name to `ENGINES`.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx
import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import JsonValue

from nestd.engine import acp as acp_module
from nestd.events import types
from nestd.pixies.call_runs import FINISHED_REPORT, INTERRUPTED_TEXT, STOPPED_TEXT
from nestd.providers.acp import AcpProbe
from nestd.providers.acp_engines import OPENCODE
from nestd.providers.acp_process import AcpLaunch, AcpTransportFactory
from nestd.providers.base import (
    CALL_PIXIE_TOOL,
    PermissionRequest,
    PlanStep,
    Question,
    QuestionOption,
    QuestionRequest,
    ToolRefusedError,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.providers.codex_rpc import JsonObject
from nestd.providers.codex_tools import TOKEN_ENV
from nestd.tracking.agents import PAUSED
from tests.acp_engine_support import FREE_MODELS, preinstall
from tests.acp_support import FakeAgent, Step, load
from tests.acp_support import FakeTransport as AcpTransport
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.codex_support import FakeTransport, item, note, turn_completed
from tests.fake_provider import RESULT, FakeRun, limited, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create

CALL = f"mcp__nest__{CALL_PIXIE_TOOL}"
# Long enough for any step here; a call that never ends fails the test instead of hanging.
STEP_SECONDS = 15


async def soon[T](waiting: Awaitable[T]) -> T:
    async with asyncio.timeout(STEP_SECONDS):
        return await waiting


ENGINES = ["claude", "codex", "acp"]
# The session id the recorded OpenCode transcript names.
ACP_SESSION = "ses_e8559c2fbffeMG37VUaTxc32MU"
QUESTION = "Which database?"


@pytest.fixture
def agent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeAgent:
    """OpenCode in memory, installed and signed in."""

    async def probe(launch: AcpLaunch, cwd: Path, transport: AcpTransportFactory) -> AcpProbe:
        del launch, cwd, transport
        return AcpProbe(models=FREE_MODELS, signed_in=True, agent_version=None, mcp_http=True)

    monkeypatch.setattr(acp_module, "probe", probe)
    login = tmp_path / "home" / ".local" / "share" / "opencode" / "auth.json"
    login.parent.mkdir(parents=True)
    login.write_text('{"opencode": {"type": "api"}}', encoding="utf-8")
    return FakeAgent(load("opencode-text", tmp_path / "repo"))


@pytest.fixture
async def api(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, agent: FakeAgent
) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets, acp=agent) as running:
        preinstall(running.ctx.paths.engines_dir, OPENCODE)
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


def acp_update(fields: dict[str, JsonValue]) -> JsonObject:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionId": ACP_SESSION, "update": fields},
    }


@dataclass
class Turn:
    """A called pixie's turn that works until the test ends it."""

    began: asyncio.Event = field(default_factory=asyncio.Event)
    go: asyncio.Event = field(default_factory=asyncio.Event)
    report: str = ""
    # Claude: its run; Codex: its app-server; ACP: its engine process and its words.
    run: FakeRun | None = None
    transport: FakeTransport | None = None
    acp: AcpTransport | None = None
    gate: str = ""
    words: JsonObject = field(default_factory=dict[str, JsonValue])


class Called:
    """The engine the called pixie runs on."""

    def __init__(self, api: Api, engine: str, agent: FakeAgent | None = None) -> None:
        self.api = api
        self.engine = engine
        self.agent = agent
        self._scripted = 0
        # The app-server each Codex turn started on, in order.
        self._starts: list[FakeTransport] = []
        if engine == "codex":
            receive = api.codex.receive

            async def noting(transport: FakeTransport, message: JsonObject) -> None:
                if message.get("method") == "turn/start":
                    self._starts.append(transport)
                await receive(transport, message)

            api.codex.receive = noting

    @property
    def provider(self) -> str:
        return OPENCODE.id if self.engine == "acp" else self.engine

    def _acp(self) -> FakeAgent:
        assert self.agent is not None
        return self.agent

    def turn(self) -> Turn:
        """Its next turn: it begins, then reports once the test says `finish`."""
        turn = Turn()
        if self.engine == "claude":

            async def play(run: FakeRun) -> None:
                turn.run = run
                await run.sink.provider_session_id("sdk-called")
                await run.sink.message(
                    [ToolUseBlock(id="b1", name="Bash", input={"command": "make test"})], None
                )
                turn.began.set()
                await turn.go.wait()
                await reply(turn.report, provider_session_id="sdk-called")(run)

            self.api.provider.script(play)
        elif self.engine == "acp":
            self._acp_turn(turn)
        else:
            self._scripted += 1
            index = self._scripted
            self.api.codex.script(
                note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
                item(
                    "started",
                    {"type": "commandExecution", "id": "b1", "command": "make test"},
                ),
            )

            async def began() -> None:
                await until(lambda: len(self._starts) >= index, STEP_SECONDS)
                turn.transport = self._starts[index - 1]
                turn.began.set()

            asyncio.get_running_loop().create_task(began())
        return turn

    def _acp_turn(self, turn: Turn) -> None:
        agent = self._acp()
        self._scripted += 1
        index = self._scripted
        turn.gate = f"gate-{index}"
        turn.words = acp_update(
            {
                "sessionUpdate": "agent_message_chunk",
                "messageId": f"m{index}",
                "content": {"type": "text", "text": ""},
            }
        )
        shell = {
            "sessionUpdate": "tool_call",
            "toolCallId": "b1",
            "title": "make test",
            "kind": "execute",
            "status": "in_progress",
            "rawInput": {"command": "make test"},
        }
        agent.queue(
            "session/prompt",
            [
                Step("push", acp_update(cast("dict[str, JsonValue]", shell))),
                Step("expect", {"method": turn.gate}),
                Step("push", turn.words),
                Step("answer", {"result": {"stopReason": "end_turn"}}),
            ],
        )

        async def began() -> None:
            await until(lambda: len(agent.asked_on.get("session/prompt", [])) >= index, 15)
            turn.acp = agent.asked_on["session/prompt"][index - 1]
            turn.began.set()

        asyncio.get_running_loop().create_task(began())

    async def finish(self, turn: Turn, report: str) -> None:
        await soon(turn.began.wait())
        turn.report = report
        if self.engine == "claude":
            turn.go.set()
            return
        if self.engine == "acp":
            update = cast("JsonObject", cast("JsonObject", turn.words["params"])["update"])
            cast("JsonObject", update["content"])["text"] = report
            self._acp().release(turn.gate)
            return
        assert turn.transport is not None
        turn.transport.push(item("completed", {"type": "agentMessage", "id": "a1", "text": report}))
        turn.transport.push(turn_completed())

    async def ask(self, turn: Turn) -> str:
        """The called pixie asks to run a command; how it was answered."""
        await soon(turn.began.wait())
        if self.engine == "claude":
            assert turn.run is not None
            decision = await turn.run.handler.decide(
                PermissionRequest("Bash", {"command": "npm install"})
            )
            return decision.behavior
        if self.engine == "acp":
            assert turn.acp is not None
            asked = await self._acp().request(
                turn.acp,
                "session/request_permission",
                {
                    "sessionId": ACP_SESSION,
                    "toolCall": {
                        "toolCallId": "c9",
                        "title": "npm install",
                        "kind": "execute",
                        "status": "pending",
                        "rawInput": {"command": "npm install"},
                    },
                    "options": [
                        {"optionId": "once", "kind": "allow_once", "name": "Allow once"},
                        {"optionId": "reject", "kind": "reject_once", "name": "Reject"},
                    ],
                },
            )
            outcome = cast("JsonObject", cast("JsonObject", asked["result"])["outcome"])
            return "allow" if outcome.get("optionId") == "once" else "deny"
        answer = await self.api.codex.request(
            "item/commandExecution/requestApproval", {"command": "npm install", "itemId": "c9"}
        )
        result = cast("JsonObject", answer["result"])
        return "allow" if result["decision"] in ("accept", "acceptForSession") else "deny"

    async def plan(self, turn: Turn, steps: list[PlanStep]) -> None:
        await soon(turn.began.wait())
        if self.engine == "claude":
            assert turn.run is not None
            await turn.run.sink.plan(steps, None)
            return
        if self.engine == "acp":
            assert turn.acp is not None
            entries: list[JsonValue] = [
                {"content": s.text, "priority": "medium", "status": s.status} for s in steps
            ]
            turn.acp.push(acp_update({"sessionUpdate": "plan", "entries": entries}))
            return
        assert turn.transport is not None
        turn.transport.push(
            note(
                "turn/plan/updated",
                threadId="thread-1",
                turnId="turn-1",
                plan=[{"step": s.text, "status": _codex_status(s.status)} for s in steps],
            )
        )

    async def question(self, turn: Turn) -> str | None:
        """The called pixie asks the user a question its engine's own way; the answer."""
        await soon(turn.began.wait())
        if self.engine == "claude":
            assert turn.run is not None
            option = QuestionOption("SQLite", None)
            answer = await turn.run.handler.ask(
                QuestionRequest(questions=(Question(QUESTION, "Database", (option,), False),))
            )
            return (answer.answers or {}).get(QUESTION)
        if self.engine == "codex":
            asked = await self.api.codex.request(
                "item/tool/requestUserInput",
                {
                    "threadId": "thread-1",
                    "turnId": "turn-1",
                    "itemId": "q1",
                    "questions": [
                        {
                            "id": "db",
                            "header": "Database",
                            "question": QUESTION,
                            "options": [{"label": "SQLite", "description": ""}],
                        }
                    ],
                },
            )
            answers = cast("JsonObject", cast("JsonObject", asked["result"])["answers"])
            return str(cast("list[str]", cast("JsonObject", answers["db"])["answers"])[0])
        [*_, new] = self._acp().requests("session/new")
        servers = cast("list[dict[str, Any]]", new["mcpServers"])
        [server] = [s for s in servers if s["name"] == "nest"]
        headers: dict[str, str] = {h["name"]: h["value"] for h in server["headers"]}
        async with (
            httpx2.AsyncClient(headers=headers) as http,
            streamable_http_client(str(server["url"]), http_client=http) as (read, write),
            ClientSession(read, write) as session,
        ):
            await session.initialize()
            result = await session.call_tool(
                "ask_user",
                {
                    "questions": [
                        {
                            "question": QUESTION,
                            "header": "Database",
                            "options": [
                                {"label": "SQLite", "description": "One file."},
                                {"label": "Postgres", "description": "A server."},
                            ],
                            "multiSelect": False,
                        }
                    ]
                },
            )
        text = str(result.content[0].model_dump()["text"])
        return "SQLite" if '"SQLite"' in text else None

    def limited(self) -> None:
        """Its next turn is cut off by the usage limit."""
        if self.engine == "claude":
            self.api.provider.script(limited())
            return
        error: JsonObject = {"message": "limit", "codexErrorInfo": "usageLimitExceeded"}
        self.api.codex.script(
            note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
            turn_completed("failed", error=error),
        )

    def resumed(self) -> bool:
        """Whether its latest run continued its earlier conversation."""
        if self.engine == "claude":
            return self.api.provider.runs[-1].spec.resume_id == "sdk-called"
        if self.engine == "acp":
            return bool(self._acp().requests("session/resume"))
        return bool(self.api.codex.requests("thread/resume"))


def _codex_status(status: str) -> str:
    return {"in_progress": "inProgress"}.get(status, status)


class Caller:
    """The calling chat, on the other engine: it calls the pixie with call_pixie as its
    engine would and gets the tool's result.
    """

    def __init__(self, api: Api, engine: str) -> None:
        self.api = api
        self.engine = engine
        self.chat_id = ""
        self.run: FakeRun | None = None
        self._calls: asyncio.Queue[tuple[dict[str, JsonValue], asyncio.Future[str]] | None] = (
            asyncio.Queue()
        )
        self._next = 0
        self._codex: FakeTransport | None = None

    async def open(self, permission_mode: str = "default", mode: str = "in_place") -> None:
        if self.engine == "claude":
            self.api.provider.steering = True
            self.api.provider.script(self._turn)
            chat = await create(self.api, mode=mode, permission_mode=permission_mode)
            self.chat_id = str(chat["id"])
            await until(lambda: self.run is not None)
            return
        self.api.codex.script(note("turn/started", threadId="thread-1", turn={"id": "turn-1"}))
        chat = await create(self.api, provider="codex", mode=mode, permission_mode=permission_mode)
        self.chat_id = str(chat["id"])
        await until(lambda: bool(self.api.codex.requests("turn/start")))
        self._codex = self.api.codex.transport

    async def _turn(self, run: FakeRun) -> None:
        self.run = run
        await run.sink.provider_session_id("sdk-caller")
        while (request := await self._calls.get()) is not None:
            args, done = request
            self._next += 1
            tool_id = f"tu{self._next}"
            await run.sink.message([ToolUseBlock(id=tool_id, name=CALL, input=args)], None)
            tool = next(t for t in run.spec.nest_tools if t.name == CALL_PIXIE_TOOL)
            try:
                text, failed = await tool.handler(args), False
            except ToolRefusedError as error:
                text, failed = str(error), True
            await run.sink.message(
                [ToolResultBlock(tool_use_id=tool_id, content=text, is_error=failed)], None
            )
            done.set_result(("ERROR: " if failed else "") + text)
        await reply("Done.", provider_session_id="sdk-caller")(run)

    async def call(self, **args: JsonValue) -> str:
        """The tool's result: its text, or `ERROR: ...` when it was refused or failed."""
        if self.engine == "claude":
            done: asyncio.Future[str] = asyncio.get_running_loop().create_future()
            await self._calls.put((dict(args), done))
            return await soon(done)
        self._next += 1
        tool_id = f"tu{self._next}"
        assert self._codex is not None
        call: JsonObject = {
            "type": "mcpToolCall",
            "id": tool_id,
            "server": "nest",
            "tool": CALL_PIXIE_TOOL,
            "arguments": dict(args),
            "status": "inProgress",
        }
        self._codex.push(item("started", call))
        await until(lambda: self._tool_seen(tool_id))
        answer = await self._mcp(dict(args))
        result = cast("JsonObject", answer["result"])
        failed = result.get("isError") is True
        status = "failed" if failed else "completed"
        error: JsonValue = None
        if failed:
            error = {"message": cast("list[JsonObject]", result["content"])[0]["text"]}
        self._codex.push(
            item("completed", {**call, "status": status, "result": result, "error": error})
        )
        content = cast("list[JsonObject]", result["content"])
        text = "\n".join(str(c.get("text", "")) for c in content)
        return ("ERROR: " if failed else "") + text

    async def _tool_seen(self, tool_id: str) -> bool:
        events = (await self.api.http.get(f"/api/sessions/{self.chat_id}/events")).json()
        return any(
            block.get("id") == tool_id
            for e in events
            if e["type"] == types.SESSION_MESSAGE
            for block in e["payload"]["blocks"]
        )

    async def _mcp(self, args: dict[str, JsonValue]) -> JsonObject:
        [start] = self.api.codex.requests("thread/start")[:1]
        nest = cast("JsonObject", cast("JsonObject", start["config"])["mcp_servers.nest"])
        [launch] = [launch for launch in self.api.codex.launches if launch.cwd is not None][:1]
        async with httpx.AsyncClient(timeout=30) as http:
            response = await http.post(
                str(nest["url"]),
                headers={
                    "Authorization": f"Bearer {launch.env[TOKEN_ENV]}",
                    "Accept": "application/json, text/event-stream",
                    "MCP-Protocol-Version": "2025-06-18",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": CALL_PIXIE_TOOL, "arguments": args},
                },
            )
        return cast("JsonObject", json.loads(response.text))

    async def steered(self) -> str:
        """The text written into the caller's running turn, once its engine took it."""
        if self.engine == "claude":
            run = self.run
            assert run is not None
            await until(lambda: bool(run.steered))
            [read] = await run.read_steered()
            return read.text
        await until(lambda: bool(self.api.codex.requests("turn/steer")))
        [steer] = self.api.codex.requests("turn/steer")[-1:]
        assert self._codex is not None
        self._codex.push(
            item(
                "started",
                {"type": "userMessage", "id": "u2", "clientId": steer["clientUserMessageId"]},
            )
        )
        words = cast("list[JsonObject]", steer["input"])
        return "\n".join(str(w.get("text", "")) for w in words)

    async def end_turn(self) -> None:
        if self.engine == "claude":
            await self._calls.put(None)
            return
        assert self._codex is not None
        self._codex.push(turn_completed())


@dataclass
class Scene:
    api: Api
    called: Called
    caller: Caller
    pixie_id: str = ""

    async def pixie(self, name: str = "Coder", **fields: object) -> str:
        body = {"name": name, "provider": self.called.provider, **fields}
        response = await self.api.http.post("/api/pixies", json=body)
        assert response.status_code == 201, response.text
        self.pixie_id = str(response.json()["id"])
        return self.pixie_id

    async def called_sessions(self) -> list[dict[str, Any]]:
        rows = await self.api.ctx.db.fetch_all(
            "SELECT id FROM sessions WHERE called_by = ? ORDER BY rowid", (self.caller.chat_id,)
        )
        return [(await self.api.http.get(f"/api/sessions/{row['id']}")).json() for row in rows]

    async def detail(self) -> dict[str, Any]:
        return (await self.api.http.get(f"/api/sessions/{self.caller.chat_id}")).json()

    async def row(self, tool_id: str) -> dict[str, Any] | None:
        agents = (await self.detail())["agents"]
        return next((a for a in agents if a["id"] == tool_id), None)

    async def results(self) -> list[dict[str, Any]]:
        """The `pixie_result` lines the caller got."""
        events = (await self.api.http.get(f"/api/sessions/{self.caller.chat_id}/events")).json()
        return [
            e["payload"]
            for e in events
            if e["type"] == types.SESSION_USER_MESSAGE
            and e["payload"].get("origin") == "pixie_result"
        ]


@pytest.fixture(params=ENGINES)
async def scene(api: Api, agent: FakeAgent, request: pytest.FixtureRequest) -> Scene:
    engine = str(request.param)
    # The caller is on another engine, so the call crosses engines.
    caller = Caller(api, "codex" if engine == "claude" else "claude")
    return Scene(api, Called(api, engine, agent), caller)


async def test_a_call_is_a_subagent_row_with_its_work_and_report(scene: Scene) -> None:
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Run the tests"))
    await soon(turn.began.wait())
    await until(lambda: _activity(scene, "tu1", "Bash make test"))
    await scene.called.finish(turn, "All 12 pass.")

    assert await soon(calling) == "All 12 pass."
    row = await scene.row("tu1")
    assert row is not None
    assert (row["name"], row["status"]) == ("coder", "done")
    [work] = (
        await scene.api.http.get(
            f"/api/sessions/{scene.caller.chat_id}/pixies/{scene.pixie_id}/calls"
        )
    ).json()
    assert (work["prompt"], work["report"], work["state"]) == (
        "Run the tests",
        "All 12 pass.",
        "done",
    )
    assert any(block.get("name") == "Bash" for m in work["messages"] for block in m["blocks"])


async def _activity(scene: Scene, tool_id: str, activity: str) -> bool:
    row = await scene.row(tool_id)
    return row is not None and row["activity"] == activity


async def test_a_background_call_reports_into_an_idle_caller(scene: Scene) -> None:
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()

    started = await soon(scene.caller.call(pixie="coder", task="Refactor", run_in_background=True))
    await scene.caller.end_turn()
    if scene.caller.engine == "claude":
        scene.api.provider.script(reply("Thanks."))
    else:
        scene.api.codex.script(note("turn/started", threadId="thread-1", turn={"id": "turn-1"}))
    await scene.called.finish(turn, "Refactored.")

    assert "working in the background" in started
    await until(lambda: _result_count(scene, 1))
    [result] = await scene.results()
    assert result["status"] == "done"
    assert result["pixie_id"] == scene.pixie_id
    assert "Refactored." in result["text"]
    await until(lambda: _row_status(scene, "tu1", "done"))


async def _result_count(scene: Scene, count: int) -> bool:
    return len(await scene.results()) == count


async def _row_status(scene: Scene, tool_id: str, status: str) -> bool:
    row = await scene.row(tool_id)
    return row is not None and row["status"] == status


async def test_a_background_report_goes_into_a_running_turn(scene: Scene) -> None:
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()

    await soon(scene.caller.call(pixie="coder", task="Refactor", run_in_background=True))
    await scene.called.finish(turn, "Refactored.")

    assert "Refactored." in await scene.caller.steered()
    await until(lambda: _result_count(scene, 1))
    [shown] = await scene.results()
    assert shown["status"] == "done"
    await scene.caller.end_turn()


async def test_a_question_is_the_callers_and_answers_the_called_run(scene: Scene) -> None:
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()
    chat = await scene.detail()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Set up the database"))
    asking = asyncio.create_task(scene.called.question(turn))

    async def pending() -> list[dict[str, Any]]:
        listed = (await scene.api.http.get("/api/approvals", params={"status": "pending"})).json()
        return [a for a in cast("list[dict[str, Any]]", listed) if a["kind"] == "question"]

    await until(lambda: _non_empty(pending()))
    [question] = await pending()
    assert (question["session_id"], question["title"]) == (scene.caller.chat_id, chat["title"])
    assert question["payload"]["questions"][0]["question"] == QUESTION
    resolved = await scene.api.http.post(
        f"/api/approvals/{question['id']}/resolve", json={"answers": {QUESTION: "SQLite"}}
    )
    assert resolved.status_code == 200, resolved.text
    assert await soon(asking) == "SQLite"
    await scene.called.finish(turn, "SQLite it is.")
    assert await soon(calling) == "SQLite it is."


async def test_a_report_naming_a_team_reaches_the_caller_as_written(api: Api) -> None:
    """A daemon message is no call: a team it names adds no instruction (B112)."""
    scene = Scene(api, Called(api, "codex"), Caller(api, "claude"))
    team = (
        await scene.api.http.post("/api/pixie-teams", json={"name": "QA", "handle": "qa"})
    ).json()
    for name in ("Lead", "Bugs"):
        created = await scene.api.http.post("/api/pixies", json={"name": name})
        await scene.api.http.patch(
            f"/api/pixies/{created.json()['id']}", json={"team_id": team["id"]}
        )
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()

    await soon(scene.caller.call(pixie="coder", task="Review", run_in_background=True))
    await scene.called.finish(turn, "Looks good; ask @qa to test it.")

    steered = await scene.caller.steered()
    assert steered == FINISHED_REPORT.format(slug="coder", report="Looks good; ask @qa to test it.")
    await scene.caller.end_turn()


async def test_a_background_call_ends_cleanly_when_the_daemon_stops(
    tmp_path: Path,
    clock: FakeClock,
    secrets: FakeSecretStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    async with running_api(tmp_path, clock, secrets) as api:
        await api.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        scene = Scene(api, Called(api, "codex"), Caller(api, "claude"))
        await scene.pixie()
        scene.called.turn()
        await scene.caller.open()
        await soon(scene.caller.call(pixie="coder", task="Long", run_in_background=True))

    # The daemon stopped with the call running: it ended with it, without an error, and
    # no task of it is left to touch the closed database.
    assert not [r for r in caplog.records if r.name == "nestd.pixies.call_runs"]
    left = [t for t in asyncio.all_tasks() if "_in_background" in repr(t.get_coro())]
    assert not [t for t in left if not t.done()]


async def test_parallel_calls_each_report(scene: Scene) -> None:
    await scene.pixie("Coder")
    await scene.pixie("Tester")
    first, second = scene.called.turn(), scene.called.turn()
    await scene.caller.open()

    await soon(scene.caller.call(pixie="coder", task="Code", run_in_background=True))
    await soon(scene.caller.call(pixie="tester", task="Test", run_in_background=True))
    await scene.caller.end_turn()
    for _ in range(2):
        if scene.caller.engine == "claude":
            scene.api.provider.script(reply("Noted."))
        else:
            scene.api.codex.script(
                note("turn/started", threadId="thread-1", turn={"id": "turn-1"}), turn_completed()
            )
    await scene.called.finish(first, "Coded.")
    await until(lambda: _result_count(scene, 1))
    await until(lambda: _caller_idle(scene.api, scene.caller.chat_id))
    await scene.called.finish(second, "Tested.")

    await until(lambda: _result_count(scene, 2))
    assert len(await scene.called_sessions()) == 2


@pytest.mark.parametrize("fresh", [False, True])
async def test_calling_again_continues_unless_fresh(scene: Scene, fresh: bool) -> None:
    await scene.pixie()
    first, second = scene.called.turn(), scene.called.turn()
    await scene.caller.open()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Start"))
    await scene.called.finish(first, "Started.")
    assert await soon(calling) == "Started."
    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Go on", fresh=fresh))
    await scene.called.finish(second, "Went on.")

    assert await soon(calling) == "Went on."
    sessions = await scene.called_sessions()
    assert len(sessions) == (2 if fresh else 1)
    assert scene.called.resumed() is not fresh
    [entry] = (await scene.api.http.get(f"/api/sessions/{scene.caller.chat_id}/pixies")).json()
    assert [c["continued"] for c in entry["calls"]] == [not fresh, False]


async def test_a_called_pixie_keeps_its_own_mode(scene: Scene) -> None:
    await scene.pixie(permission_mode="bypassPermissions")
    turn = scene.called.turn()
    await scene.caller.open(permission_mode="default")

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Go"))
    await soon(turn.began.wait())
    [called] = await scene.called_sessions()
    await scene.called.finish(turn, "Ok.")

    assert called["permission_mode"] == "bypassPermissions"
    assert await soon(calling) == "Ok."


async def test_a_read_pixie_cannot_edit_the_callers_folder(scene: Scene) -> None:
    await scene.pixie(project_access="read")
    turn = scene.called.turn()
    await scene.caller.open()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Look"))
    await soon(turn.began.wait())
    repo = scene.api.ctx.repos.get("repo").path
    if scene.called.engine == "claude":
        assert turn.run is not None
        spec = turn.run.spec
        assert spec.write_root is not None
        assert not repo.is_relative_to(spec.write_root)
        assert "Edit" in spec.disallowed_tools
        assert spec.guard_git
    elif scene.called.engine == "acp":
        assert turn.acp is not None
        assert scene.called.agent is not None
        target = repo / "edited.txt"
        answer = await scene.called.agent.request(
            turn.acp,
            "fs/write_text_file",
            {"sessionId": ACP_SESSION, "path": str(target), "content": "x"},
        )
        assert "error" in answer
        assert not target.exists()
    else:
        [start] = scene.api.codex.requests("thread/start")[-1:]
        assert start["approvalPolicy"] == "untrusted"
    await scene.called.finish(turn, "Looked.")
    assert await soon(calling) == "Looked."


async def test_its_approval_is_the_callers_and_answers_the_called_run(scene: Scene) -> None:
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()
    chat = await scene.detail()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Install"))
    asking = asyncio.create_task(scene.called.ask(turn))

    async def pending() -> list[dict[str, Any]]:
        listed = (await scene.api.http.get("/api/approvals", params={"status": "pending"})).json()
        return cast("list[dict[str, Any]]", listed)

    await until(lambda: _non_empty(pending()))
    [approval] = await pending()
    assert (approval["session_id"], approval["repo"], approval["title"]) == (
        scene.caller.chat_id,
        chat["repo"],
        chat["title"],
    )
    resolved = await scene.api.http.post(
        f"/api/approvals/{approval['id']}/resolve", json={"behavior": "allow"}
    )
    assert resolved.status_code == 200, resolved.text
    assert await soon(asking) == "allow"
    await scene.called.finish(turn, "Installed.")
    assert await soon(calling) == "Installed."


async def _non_empty(items: Awaitable[list[dict[str, Any]]]) -> bool:
    return bool(await items)


async def test_the_rows_stop_ends_the_call(scene: Scene) -> None:
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Take long"))
    await soon(turn.began.wait())
    stopped = await scene.api.http.post(f"/api/sessions/{scene.caller.chat_id}/tasks/tu1/stop")

    assert stopped.status_code == 202, stopped.text
    assert await soon(calling) == "ERROR: " + STOPPED_TEXT.format(slug="coder")
    [called] = await scene.called_sessions()
    assert called["state"] == "interrupted"
    await until(lambda: _row_status(scene, "tu1", "failed"))


async def test_a_called_pixie_pauses_at_the_usage_limit_and_goes_on(
    scene: Scene, clock: FakeClock
) -> None:
    if scene.called.engine == "acp":
        pytest.skip("ACP engines report no usage limit, so there is no pause to make")
    await scene.pixie()
    scene.called.limited()
    later = scene.called.turn()
    await scene.caller.open()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Big job"))

    async def paused() -> bool:
        sessions = await scene.called_sessions()
        return bool(sessions) and sessions[0]["limit_pause"] is not None

    await until(paused)
    await until(lambda: _activity(scene, "tu1", PAUSED))
    assert not calling.done()
    clock.advance(timedelta(hours=3))
    await scene.api.ctx.sessions.tick_limits()
    await scene.called.finish(later, "Done after the reset.")

    assert await soon(calling) == "Done after the reset."


async def test_a_plan_feeds_goals_and_shows_on_the_row(scene: Scene) -> None:
    await scene.pixie()
    turn = scene.called.turn()
    await scene.caller.open()

    calling = asyncio.create_task(scene.caller.call(pixie="coder", task="Plan it"))
    steps = [
        PlanStep(text="Read", status="completed"),
        PlanStep(text="Write", status="in_progress"),
    ]
    await scene.called.plan(turn, steps)

    await until(lambda: _activity(scene, "tu1", "Write"))
    [called] = await scene.called_sessions()
    assert [(t["subject"], t["status"]) for t in called["tasks"]] == [
        ("Read", "completed"),
        ("Write", "in_progress"),
    ]
    await scene.called.finish(turn, "Planned.")
    assert await soon(calling) == "Planned."


async def test_a_restart_interrupts_a_background_call_and_tells_the_caller(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore
) -> None:
    async with running_api(tmp_path, clock, secrets) as api:
        await api.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        scene = Scene(api, Called(api, "codex"), Caller(api, "claude"))
        await scene.pixie()
        scene.called.turn()
        await scene.caller.open()
        await soon(scene.caller.call(pixie="coder", task="Long", run_in_background=True))
        await scene.caller.end_turn()
        chat_id = scene.caller.chat_id
        await until(lambda: _caller_idle(api, chat_id))

    async with running_api(tmp_path, clock, secrets) as again:
        again.provider.script(reply("I'll call it again."))
        scene = Scene(again, Called(again, "codex"), Caller(again, "claude"))
        scene.caller.chat_id = chat_id

        await until(lambda: _result_count(scene, 1))
        [result] = await scene.results()
        assert result["status"] == "interrupted"
        assert result["text"] == INTERRUPTED_TEXT.format(slug="coder")


async def _caller_idle(api: Api, chat_id: str) -> bool:
    return (await api.http.get(f"/api/sessions/{chat_id}")).json()["state"] == "idle"


async def test_a_plan_replaces_the_task_list_of_the_main_agent(api: Api) -> None:
    """The plan of an engine's own (Codex, ACP) feeds Goals like TaskCreate (B112)."""

    async def turn(run: FakeRun) -> None:
        await run.sink.provider_session_id("sdk-1")
        await run.sink.plan([PlanStep(text="One", status="pending")], None)
        await run.sink.plan(
            [PlanStep(text="One", status="completed"), PlanStep(text="Two", status="pending")],
            None,
        )
        await run.sink.result(RESULT)

    api.provider.script(turn)
    chat_id = str((await create(api, mode="in_place"))["id"])

    async def planned() -> bool:
        tasks = (await api.http.get(f"/api/sessions/{chat_id}")).json()["tasks"]
        return [(t["id"], t["subject"], t["status"]) for t in tasks] == [
            ("1", "One", "completed"),
            ("2", "Two", "pending"),
        ]

    await until(planned)
    goals = (await api.http.get("/api/goals", params={"repo": "repo"})).json()
    assert [g["session_id"] for g in goals] == [chat_id]
