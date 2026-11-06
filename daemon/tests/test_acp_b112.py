"""B112 on ACP engines: the engine's plan as the task list, questions through Nest's
`ask_user`, and a pixie's skills named in its first message.
"""

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

import httpx2
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from pydantic import JsonValue

from nestd.providers.acp import ACP_UNSUPPORTED, AcpLaunch, AcpProvider, AcpRun
from nestd.providers.acp_engines import OPENCODE
from nestd.providers.acp_questions import NOT_ANSWERED, ask_user_tool
from nestd.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    PlanStep,
    QuestionAnswer,
    QuestionOption,
    QuestionRequest,
    RunAccount,
    SessionSpec,
    ToolRefusedError,
)
from tests.acp_support import FakeAgent, Step, load
from tests.api_client import Api, running_api, wants_loops
from tests.fakes import FakeClock, FakeSecretStore
from tests.recording_sink import RecordingSink
from tests.test_acp_provider import results, turn, update


class Asked:
    """A question handler that answers with `answer`, or waits forever without one."""

    def __init__(self, answer: QuestionAnswer | None) -> None:
        self.requests: list[QuestionRequest] = []
        self.cancelled = False
        self._answer = answer

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision("allow")

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        self.requests.append(request)
        if self._answer is not None:
            return self._answer
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        raise AssertionError


async def open_run(
    agent: FakeAgent, cwd: Path, handler: Asked | None = None, **fields: object
) -> tuple[AcpRun, RecordingSink]:
    async def launcher(account: RunAccount | None) -> AcpLaunch:
        return AcpLaunch(("/engines/opencode", "acp"), {})

    values: dict[str, object] = {"cwd": cwd, "permission_mode": "default", "guard_git": False}
    values.update(fields)
    sink = RecordingSink()
    provider = AcpProvider(OPENCODE, launcher, transport=agent)
    run = await provider.open(SessionSpec(**values), handler or Asked(None), sink)  # type: ignore[arg-type]
    return run, sink


@asynccontextmanager
async def nest_server(agent: FakeAgent) -> AsyncGenerator[ClientSession]:
    """The MCP client the engine would be, on the `nest` server the session was given."""
    [new] = agent.requests("session/new")
    servers = cast("list[dict[str, Any]]", new["mcpServers"])
    [server] = [s for s in servers if s["name"] == "nest"]
    headers: dict[str, str] = {h["name"]: h["value"] for h in server["headers"]}
    async with (
        httpx2.AsyncClient(headers=headers) as http,
        streamable_http_client(str(server["url"]), http_client=http) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


QUESTIONS: dict[str, JsonValue] = {
    "questions": [
        {
            "question": "Which database should we use?",
            "header": "Database",
            "options": [
                {"label": "SQLite (Recommended)", "description": "One file, no server."},
                {"label": "Postgres", "description": "A server of its own."},
            ],
            "multiSelect": False,
        }
    ]
}


async def test_the_engines_plan_is_the_chats_task_list(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    entries: list[JsonValue] = [
        {"content": "Read the code", "priority": "high", "status": "completed"},
        {"content": "Fix the bug", "priority": "high", "status": "in_progress"},
        {"content": "Run the tests", "priority": "low", "status": "pending"},
    ]
    agent.script(
        "session/prompt",
        [
            Step("push", update({"sessionUpdate": "plan", "entries": entries})),
            Step("answer", {"result": {"stopReason": "end_turn"}}),
        ],
    )
    run, sink = await open_run(agent, tmp_path)

    await turn(run, sink)

    plans = [value for kind, value in sink.calls if kind == "plan"]
    assert plans == [
        (
            [
                PlanStep(text="Read the code", status="completed"),
                PlanStep(text="Fix the bug", status="in_progress"),
                PlanStep(text="Run the tests", status="pending"),
            ],
            None,
        )
    ]
    assert {"questions", "task_list", "stop_task"}.isdisjoint(ACP_UNSUPPORTED)
    await run.close()


async def test_ask_user_asks_through_the_runs_question_handler(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    handler = Asked(QuestionAnswer({"Which database should we use?": "Postgres"}))
    run, _ = await open_run(agent, tmp_path, handler)

    async with nest_server(agent) as engine:
        listed = await engine.list_tools()
        result = await engine.call_tool("ask_user", QUESTIONS)

    assert "ask_user" in [tool.name for tool in listed.tools]
    [request] = handler.requests
    [question] = request.questions
    # The same question as Claude's AskUserQuestion makes, for the same card in Needs you.
    assert (question.header, question.multi_select) == ("Database", False)
    assert question.options == (
        QuestionOption("SQLite", "One file, no server.", recommended=True),
        QuestionOption("Postgres", "A server of its own."),
    )
    assert not result.is_error
    [text] = [part.model_dump()["text"] for part in result.content]
    assert '"Which database should we use?"="Postgres"' in text
    await run.close()


async def test_a_dismissed_question_is_the_tools_error(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, _ = await open_run(agent, tmp_path, Asked(QuestionAnswer(None, "Not now.")))

    async with nest_server(agent) as engine:
        result = await engine.call_tool("ask_user", QUESTIONS)

    assert result.is_error
    assert [part.model_dump()["text"] for part in result.content] == ["Not now."]
    await run.close()


async def test_a_question_is_withdrawn_before_the_engine_stops_waiting() -> None:
    handler = Asked(None)
    tool = ask_user_tool(handler, timedelta(seconds=30.05))

    with pytest.raises(ToolRefusedError, match="did not answer in time") as refused:
        await tool.handler(QUESTIONS)

    assert str(refused.value) == NOT_ANSWERED
    # The wait was cancelled, which takes the card out of Needs you.
    assert handler.cancelled


async def test_a_pixies_skills_are_named_in_its_first_message(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, sink = await open_run(
        agent, tmp_path, system_prompt_append="You are Ada.", skills=("review", "deploy")
    )

    await turn(run, sink)

    [prompt] = agent.requests("session/prompt")
    lead = str(cast("list[dict[str, Any]]", prompt["prompt"])[0]["text"])
    assert lead.startswith("You are Ada.")
    assert "Use only these skills in this chat: review, deploy." in lead
    assert results(sink)[-1].subtype == "success"
    await run.close()


@pytest.fixture
async def api(
    tmp_path: Path, clock: FakeClock, secrets: FakeSecretStore, request: pytest.FixtureRequest
) -> AsyncIterator[Api]:
    async with running_api(tmp_path, clock, secrets, loops=wants_loops(request)) as running:
        yield running


async def test_a_pixie_on_an_acp_engine_keeps_its_skill_list(api: Api) -> None:
    """Its skills are named in its first message, so the list is no longer refused."""
    created = await api.http.post(
        "/api/pixies", json={"name": "O", "provider": "opencode", "skills": ["review"]}
    )

    assert created.status_code == 201
    assert created.json()["skills"] == ["review"]
    assert "pixie_skills" not in ACP_UNSUPPORTED
