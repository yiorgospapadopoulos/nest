"""B91 stage 2: pixie calls across engines. A pixie on Codex, or any pixie a Codex run
calls, runs as a session of its own in the caller's folder; the call waits for it and
returns its report. Claude-to-Claude calls stay subagents.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import cast

import httpx
import pytest
from pydantic import JsonValue

from nestd.events import types
from nestd.providers.base import (
    CALL_PIXIE_TOOL,
    AgentTool,
    TextBlock,
    ToolRefusedError,
    ToolResultBlock,
    ToolUseBlock,
)
from nestd.providers.codex_engine import NOT_SIGNED_IN
from nestd.providers.codex_rpc import JsonObject
from nestd.providers.codex_tools import TOKEN_ENV
from tests.api_client import Api, running_api
from tests.async_support import until
from tests.codex_support import item, note, turn_completed
from tests.fake_provider import RESULT, FakeRun, Turn, limited, reply
from tests.fakes import FakeClock, FakeSecretStore
from tests.git_support import init_repo
from tests.test_api_sessions import create, reach

CALL = f"mcp__nest__{CALL_PIXIE_TOOL}"


@pytest.fixture
async def api(tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets) as running:
        await running.http.post("/api/repos", json={"path": str(init_repo(tmp_path / "repo"))})
        yield running


def _call_tool(run: FakeRun) -> AgentTool:
    return next(tool for tool in run.spec.nest_tools if tool.name == CALL_PIXIE_TOOL)


def calls(slug: str, task: str, outcome: list[str]) -> Turn:
    """A Claude turn that calls a pixie with the call tool, as Claude Code would."""

    async def turn(run: FakeRun) -> None:
        await run.sink.provider_session_id("sdk-1")
        args: dict[str, JsonValue] = {"pixie": slug, "task": task}
        await run.sink.message([ToolUseBlock(id="tu1", name=CALL, input=args)], None)
        try:
            text = await _call_tool(run).handler(args)
            failed = False
        except ToolRefusedError as error:
            text, failed = str(error), True
        outcome.append(text)
        await run.sink.message(
            [ToolResultBlock(tool_use_id="tu1", content=text, is_error=failed)], None
        )
        await run.sink.message([TextBlock(text="Done.")], None)
        await run.sink.result(RESULT)

    return turn


def codex_report(text: str) -> list[JsonObject]:
    return [
        note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
        item("completed", {"type": "agentMessage", "id": "a0", "text": "Looking."}),
        item("completed", {"type": "agentMessage", "id": "a1", "text": text}),
        turn_completed(),
    ]


async def _pixie(api: Api, name: str, **fields: object) -> str:
    response = await api.http.post("/api/pixies", json={"name": name, **fields})
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def _call_sessions(api: Api, pixie_id: str) -> list[dict[str, object]]:
    rows = await api.ctx.db.fetch_all(
        "SELECT id FROM sessions WHERE pixie_id = ? AND called_by IS NOT NULL", (pixie_id,)
    )
    return [(await api.http.get(f"/api/sessions/{row['id']}")).json() for row in rows]


async def test_a_claude_chat_calls_a_codex_pixie_and_gets_its_report(api: Api) -> None:
    coder = await _pixie(api, "Coder", provider="codex", model="gpt-5.5")
    await _pixie(api, "Helper")
    api.codex.script(*codex_report("Fixed the off-by-one."))
    outcome: list[str] = []
    api.provider.script(calls("coder", "Fix the paging bug", outcome))

    chat = await create(api, mode="in_place")
    chat_id = str(chat["id"])
    await reach(api, chat_id, "idle", results=1)

    assert outcome == ["Fixed the off-by-one."]
    [run] = api.provider.runs
    # Claude's own pixies stay its subagents; the Codex one is called with the tool.
    assert list(run.spec.subagents) == ["helper"]
    assert CALL_PIXIE_TOOL in {tool.name for tool in run.spec.nest_tools}
    [called] = await _call_sessions(api, coder)
    assert called["called_by"] == chat_id
    assert (called["provider"], called["model"], called["state"]) == ("codex", "gpt-5.5", "closed")
    [start] = api.codex.requests("thread/start")
    repo = str(api.ctx.repos.get("repo").path)
    # It works in the caller's folder, guarded, with its call prompt.
    assert start["cwd"] == repo
    assert "Another chat is calling you" in str(start["developerInstructions"])
    [turn] = api.codex.requests("turn/start")
    assert turn["approvalPolicy"] == "untrusted"
    assert cast("list[JsonObject]", turn["input"])[-1]["text"] == "Fix the paging bug"
    group = (await api.http.get(f"/api/sessions/{chat_id}/pixies")).json()
    assert [(g["pixie_id"], g["state"]) for g in group] == [(coder, "done")]


async def test_a_codex_chat_calls_a_claude_pixie_through_its_mcp_server(api: Api) -> None:
    helper = await _pixie(api, "Helper")
    waiting = asyncio.Event()
    go = asyncio.Event()

    async def working(run: FakeRun) -> None:
        waiting.set()
        await go.wait()
        await reply("All tests pass.")(run)

    api.provider.script(working)
    api.codex.script(note("turn/started", threadId="thread-1", turn={"id": "turn-1"}))

    chat = await create(api, provider="codex", mode="in_place")
    chat_id = str(chat["id"])
    await until(lambda: bool(api.codex.requests("turn/start")))
    [start] = api.codex.requests("thread/start")
    nest = cast("JsonObject", cast("JsonObject", start["config"])["mcp_servers.nest"])
    [launch] = [launch for launch in api.codex.launches if launch.cwd is not None]
    called = asyncio.create_task(_mcp_call(str(nest["url"]), launch.env[TOKEN_ENV], "helper"))
    await waiting.wait()
    go.set()
    answer = await called

    assert answer["result"] == {
        "content": [{"type": "text", "text": "All tests pass."}],
        "isError": False,
    }
    [session] = await _call_sessions(api, helper)
    assert (session["called_by"], session["provider"]) == (chat_id, "fake")
    [run] = api.provider.runs
    assert run.spec.cwd == api.ctx.repos.get("repo").path
    assert run.spec.guard_git
    assert run.spec.subagents == {}


async def _mcp_call(url: str, token: str, slug: str) -> JsonObject:
    async with httpx.AsyncClient(timeout=30) as http:
        response = await http.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-06-18",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": CALL_PIXIE_TOOL,
                    "arguments": {"pixie": slug, "task": "Run the tests"},
                },
            },
        )
    return cast("JsonObject", json.loads(response.text))


@pytest.mark.parametrize(
    ("args", "refusal"),
    [
        ({"pixie": "nobody", "task": "x"}, "No pixie @nobody to call"),
        ({"pixie": "coder", "task": "  "}, "task is required"),
        ({"pixie": "coder"}, "task is required"),
    ],
)
async def test_a_call_the_tool_cannot_make_is_refused(
    api: Api, args: dict[str, JsonValue], refusal: str
) -> None:
    await _pixie(api, "Coder", provider="codex")
    refused: list[str] = []

    async def turn(run: FakeRun) -> None:
        with pytest.raises(ToolRefusedError) as raised:
            await _call_tool(run).handler(args)
        refused.append(str(raised.value))
        await reply("ok")(run)

    api.provider.script(turn)
    chat_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, chat_id, "idle", results=1)

    assert refusal in refused[0]


async def test_a_team_member_is_called_only_by_its_leader(api: Api) -> None:
    team = (await api.http.post("/api/pixie-teams", json={"name": "QA", "handle": "qa"})).json()
    lead = await _pixie(api, "Lead", provider="codex")
    member = await _pixie(api, "Member", provider="codex")
    for pid in (lead, member):
        await api.http.patch(f"/api/pixies/{pid}", json={"team_id": team["id"]})
    outcome: list[str] = []
    api.provider.script(calls("member", "Do it", outcome))

    chat_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, chat_id, "idle", results=1)

    assert "member is in a team and is called only by its leader" in outcome[0]
    assert await _call_sessions(api, member) == []


async def test_a_called_pixie_that_fails_fails_the_call(api: Api) -> None:
    await _pixie(api, "Coder", provider="codex")
    api.codex.script(
        note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
        turn_completed(
            status="failed", error={"message": "model overloaded", "codexErrorInfo": None}
        ),
    )
    outcome: list[str] = []
    api.provider.script(calls("coder", "Fix it", outcome))

    chat_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, chat_id, "idle", results=1)

    assert outcome[0].startswith("@coder failed: ")
    events = (await api.http.get(f"/api/sessions/{chat_id}/events")).json()
    results = [
        block
        for e in events
        if e["type"] == types.SESSION_MESSAGE
        for block in e["payload"]["blocks"]
        if block["type"] == "tool_result"
    ]
    assert results[0]["is_error"] is True


async def test_closing_the_caller_stops_the_called_pixie(api: Api) -> None:
    coder = await _pixie(api, "Coder", provider="codex")
    api.codex.script(note("turn/started", threadId="thread-1", turn={"id": "turn-1"}))
    outcome: list[str] = []
    api.provider.script(calls("coder", "Take your time", outcome))
    chat_id = str((await create(api, mode="in_place"))["id"])

    async def called(state: str) -> bool:
        return [s["state"] for s in await _call_sessions(api, coder)] == [state]

    await until(lambda: called("running"))
    closed = await api.http.delete(f"/api/sessions/{chat_id}")

    assert closed.status_code == 200, closed.text
    await until(lambda: called("closed"))
    assert outcome == []


async def test_a_called_pixie_sends_no_notification_of_its_own(api: Api) -> None:
    coder = await _pixie(api, "Coder", provider="codex")
    api.codex.script(*codex_report("Done."))
    outcome: list[str] = []
    api.provider.script(calls("coder", "Code it", outcome))

    chat_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, chat_id, "idle", results=1)
    [called] = await _call_sessions(api, coder)
    events = (await api.http.get(f"/api/sessions/{called['id']}/events")).json()

    # The caller hears about it; the called session sends no notification of its own.
    assert outcome == ["Done."]
    assert [e for e in events if e["type"] == types.NOTIFY] == []


async def test_a_called_pixie_fails_at_the_usage_limit_instead_of_pausing(api: Api) -> None:
    helper = await _pixie(api, "Helper")
    api.provider.script(limited())
    api.codex.script(note("turn/started", threadId="thread-1", turn={"id": "turn-1"}))
    await create(api, provider="codex", mode="in_place")
    await until(lambda: bool(api.codex.requests("turn/start")))
    [start] = api.codex.requests("thread/start")
    nest = cast("JsonObject", cast("JsonObject", start["config"])["mcp_servers.nest"])
    [launch] = [launch for launch in api.codex.launches if launch.cwd is not None]

    answer = await _mcp_call(str(nest["url"]), launch.env[TOKEN_ENV], "helper")

    result = cast("JsonObject", answer["result"])
    assert result["isError"] is True
    assert "@helper failed" in json.dumps(result["content"])
    [called] = await _call_sessions(api, helper)
    assert called["limit_pause"] is None


async def test_a_called_pixie_on_a_signed_out_codex_is_refused(api: Api) -> None:
    await _pixie(api, "Coder", provider="codex")
    outcome: list[str] = []
    api.provider.script(calls("coder", "Code it", outcome))
    api.codex.answers["account/read"] = {"account": None, "requiresOpenaiAuth": True}
    await api.http.get("/api/providers", params={"refresh": True})

    chat_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, chat_id, "idle", results=1)

    assert outcome == [NOT_SIGNED_IN]


async def test_the_report_is_the_called_pixies_last_words(api: Api) -> None:
    await _pixie(api, "Coder", provider="codex")
    command = {"type": "commandExecution", "id": "c1", "command": "ls", "status": "completed"}
    api.codex.script(
        note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
        item("completed", {"type": "agentMessage", "id": "a1", "text": "First."}),
        item("completed", {**command, "aggregatedOutput": "a.py", "exitCode": 0}),
        item("completed", {"type": "agentMessage", "id": "a2", "text": "All good."}),
        turn_completed(),
    )
    outcome: list[str] = []
    api.provider.script(calls("coder", "Check", outcome))

    chat_id = str((await create(api, mode="in_place"))["id"])
    await reach(api, chat_id, "idle", results=1)

    assert outcome == ["All good."]


@pytest.mark.parametrize("how", ["interrupted", "deleted"])
async def test_a_called_pixie_stopped_on_its_own_ends_the_call(api: Api, how: str) -> None:
    coder = await _pixie(api, "Coder", provider="codex")
    api.codex.script(note("turn/started", threadId="thread-1", turn={"id": "turn-1"}))
    outcome: list[str] = []
    api.provider.script(calls("coder", "Take your time", outcome))
    chat_id = str((await create(api, mode="in_place"))["id"])

    async def running() -> bool:
        return [s["state"] for s in await _call_sessions(api, coder)] == ["running"]

    await until(running)
    [called] = await _call_sessions(api, coder)
    if how == "interrupted":
        await api.http.post(f"/api/sessions/{called['id']}/interrupt")
        await until(lambda: bool(api.codex.requests("turn/interrupt")))
        stopped = turn_completed(status="interrupted")
        api.codex.notify("turn/completed", cast("JsonObject", stopped["params"]))
    else:
        await api.http.delete(f"/api/pixies/{coder}")
    await reach(api, chat_id, "idle", results=1)

    assert outcome == ["@coder was stopped before it finished."]
    assert called["called_by"] == chat_id
