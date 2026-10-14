import asyncio
import json
import logging
from dataclasses import replace
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ProcessError,
    ResultMessage,
    SystemMessage,
    TaskNotificationMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ToolPermissionContext,
)
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport
from pydantic import JsonValue

from harness.logging_setup import ENGINE_STDERR_LOGGER
from harness.providers.base import (
    AccountInfo,
    AgentTask,
    AgentTool,
    CommandCatalog,
    ContextUsage,
    EngineDetails,
    ImageInput,
    McpServer,
    ModelOption,
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    QuestionAnswer,
    QuestionRequest,
    SessionSpec,
    SlashCommand,
    UserInput,
)
from harness.providers.claude import ClaudeProvider, ClaudeRun, build_options
from harness.providers.claude_questions import QUESTION_TIMEOUT_SECONDS
from harness.providers.git_guard import GIT_WRITE_RULES, block_git_writes
from tests.async_support import until
from tests.fake_sdk import FakeSdkClient
from tests.recording_sink import RecordingSink

RESULT = ResultMessage(
    subtype="success",
    duration_ms=1,
    duration_api_ms=1,
    is_error=False,
    num_turns=1,
    session_id="sdk-1",
)


NOT_APPROVED = PlanDecision(approved=False)


class ScriptedHandler:
    def __init__(self, decision: PermissionDecision, plan: PlanDecision = NOT_APPROVED) -> None:
        self.decision = decision
        self.plan = plan
        self.requests: list[PermissionRequest] = []
        self.plans: list[PlanRequest] = []

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return self.decision

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        return QuestionAnswer({"Which?": "A"})

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        self.plans.append(request)
        return self.plan


class Opened:
    def __init__(self, tmp_path: Path) -> None:
        self.clients: list[FakeSdkClient] = []
        self.provider = ClaudeProvider(tmp_path / "agent-gh", self.factory)
        self.sink = RecordingSink()

    def factory(self, options: ClaudeAgentOptions) -> FakeSdkClient:
        client = FakeSdkClient(options)
        self.clients.append(client)
        return client

    async def open(
        self, spec: SessionSpec, handler: ScriptedHandler | None = None
    ) -> tuple[ClaudeRun, FakeSdkClient]:
        run = await self.provider.open(
            spec, handler or ScriptedHandler(PermissionDecision("allow")), self.sink
        )
        return run, self.clients[-1]


def test_provider_name(tmp_path: Path) -> None:
    assert ClaudeProvider(tmp_path).name == "claude"


async def test_open_connects_with_the_full_option_set(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    spec = SessionSpec(
        cwd=tmp_path / "wt",
        permission_mode="acceptEdits",
        model="claude-sonnet-5",
        effort="high",
        resume_id="sdk-0",
        extra_dirs=(tmp_path / "a1", tmp_path / "a2"),
        system_prompt_append="Do not commit.",
    )

    _, client = await opened.open(spec)

    options = client.options
    assert client.connected is True
    assert options.cwd == tmp_path / "wt"
    assert options.model == "claude-sonnet-5"
    assert options.effort == "high"
    assert options.permission_mode == "acceptEdits"
    assert options.resume == "sdk-0"
    assert options.add_dirs == [tmp_path / "a1", tmp_path / "a2"]
    assert options.system_prompt == {
        "type": "preset",
        "preset": "claude_code",
        "append": "Do not commit.",
    }
    assert options.setting_sources == ["user", "project", "local"]
    assert options.include_partial_messages is True
    # Bypass is never offered to a run that did not start in it (D046).
    assert "allow-dangerously-skip-permissions" not in options.extra_args
    assert options.disallowed_tools == list(GIT_WRITE_RULES)
    assert options.hooks is not None
    git_matcher, question_matcher = options.hooks["PreToolUse"]
    # Every tool, so MCP and other shell tools are checked too (D049).
    assert git_matcher.matcher == "*"
    assert git_matcher.hooks == [block_git_writes]
    assert question_matcher.matcher == "AskUserQuestion"
    assert question_matcher.timeout == QUESTION_TIMEOUT_SECONDS
    assert options.env == {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/false",
        "GH_CONFIG_DIR": str(tmp_path / "agent-gh"),
        "GH_TOKEN": "",
        "GITHUB_TOKEN": "",
        # As the Claude app runs Claude Code (D047): answer without waiting for slow MCP
        # servers, connect them in batches, and keep old tool results in context.
        "MCP_CONNECTION_NONBLOCKING": "true",
        "MCP_SERVER_CONNECTION_BATCH_SIZE": "8",
        "DISABLE_MICROCOMPACT": "1",
    }


async def test_a_stream_message_over_a_megabyte_reaches_the_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PL-14: an image read comes back as one long line; the SDK's 1 MB default ends the run."""
    big = json.dumps({"type": "user", "data": "x" * (3 * 1024 * 1024)})
    line = tmp_path / "line.json"
    line.write_text(big + "\n", encoding="utf-8")
    cli = tmp_path / "claude"
    cli.write_text(f'#!/bin/sh\ncat "{line}"\n', encoding="utf-8")
    cli.chmod(0o755)
    monkeypatch.setenv("CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK", "1")
    spec = SessionSpec(cwd=tmp_path, permission_mode="default")
    options = build_options(spec, ScriptedHandler(PermissionDecision("allow")), tmp_path)
    transport = SubprocessCLITransport("", replace(options, cli_path=cli))

    await transport.connect()
    try:
        received = [message async for message in transport.read_messages()]
    finally:
        await transport.close()

    assert options.max_buffer_size == 64 * 1024 * 1024
    assert [len(message["data"]) for message in received] == [3 * 1024 * 1024]


async def test_minimal_spec_uses_the_plain_preset(tmp_path: Path) -> None:
    _, client = await Opened(tmp_path).open(SessionSpec(cwd=tmp_path, permission_mode="default"))

    assert client.options.system_prompt == {"type": "preset", "preset": "claude_code"}
    assert client.options.resume is None
    assert client.options.model is None
    assert client.options.effort is None
    assert client.options.add_dirs == []


async def test_permission_callback_is_bridged_to_the_handler(tmp_path: Path) -> None:
    allow = ScriptedHandler(PermissionDecision("allow"))
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"), allow)
    assert client.options.can_use_tool is not None
    context = ToolPermissionContext(tool_use_id="t1", title="Claude wants to run ls")

    result = await client.options.can_use_tool("Bash", {"command": "ls"}, context)

    assert isinstance(result, PermissionResultAllow)
    assert allow.requests == [
        PermissionRequest("Bash", {"command": "ls"}, "Claude wants to run ls")
    ]


@pytest.mark.parametrize(
    ("context", "reason"),
    [
        (ToolPermissionContext(decision_reason="A hook asks", blocked_path="/x"), "A hook asks"),
        (ToolPermissionContext(blocked_path="/Users/me/secrets"), "/Users/me/secrets"),
        (ToolPermissionContext(), None),
    ],
)
async def test_permission_requests_carry_the_engines_reason(
    tmp_path: Path, context: ToolPermissionContext, reason: str | None
) -> None:
    """BUG-44: why Claude Code asks, shown under the prompt."""
    allow = ScriptedHandler(PermissionDecision("allow"))
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"), allow)
    assert client.options.can_use_tool is not None

    await client.options.can_use_tool("Read", {"file_path": "/x"}, context)

    assert allow.requests == [PermissionRequest("Read", {"file_path": "/x"}, None, reason)]


async def test_a_crash_says_what_the_agent_wrote_to_stderr(tmp_path: Path) -> None:
    """BUG-42: instead of the SDK's "Check stderr output for details"."""
    opened = Opened(tmp_path)
    _, client = await opened.open(SessionSpec(tmp_path, "default"))
    assert client.options.stderr is not None
    noise = [f"noise {n:02} " + "." * 30 for n in range(30)]
    for line in ("Debug: starting", "", "  ", *noise):
        client.options.stderr(line)
    client.options.stderr("Error: Invalid API key \u00b7 Please run /login\n")

    client.push(
        ProcessError(
            "Command failed with exit code 1",
            exit_code=1,
            stderr="Check stderr output for details",
        )
    )
    await until(lambda: bool(opened.sink.calls))

    ((name, message),) = opened.sink.calls
    assert name == "stopped"
    assert isinstance(message, str)
    assert message.startswith("Command failed with exit code 1 (exit code: 1)\nError output: ")
    tail = message.split("Error output: ")[1]
    assert tail.endswith(f"{noise[-1]}\nError: Invalid API key \u00b7 Please run /login")
    assert "Check stderr" not in message
    # Whole lines, as many as fit.
    assert tail.startswith("noise ")
    assert 300 - 41 < len(tail) <= 300


async def test_every_stderr_line_is_logged_without_credentials(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """BUG-82: not only a crash's tail; the daemon log shows what Claude Code warned about."""
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    assert client.options.stderr is not None

    with caplog.at_level(logging.DEBUG, ENGINE_STDERR_LOGGER):
        client.options.stderr("[WARN] hook failed\n")
        client.options.stderr("   ")
        client.options.stderr("fetch https://me:ghp_secret@github.com/me/repo.git failed")

    records = [r for r in caplog.records if r.name == ENGINE_STDERR_LOGGER]
    assert [(r.levelno, r.getMessage()) for r in records] == [
        (logging.DEBUG, f"Claude Code in {tmp_path}: [WARN] hook failed"),
        (
            logging.DEBUG,
            f"Claude Code in {tmp_path}: fetch https://github.com/me/repo.git failed",
        ),
    ]


async def test_a_long_stderr_line_is_cut_to_its_end(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    _, client = await opened.open(SessionSpec(tmp_path, "default"))
    assert client.options.stderr is not None
    client.options.stderr("x" * 400)

    client.push(
        ProcessError(
            "Command failed with exit code 1",
            exit_code=1,
            stderr="Check stderr output for details",
        )
    )
    await until(lambda: bool(opened.sink.calls))

    ((_, message),) = opened.sink.calls
    assert message == (
        "Command failed with exit code 1 (exit code: 1)\nError output: ..." + "x" * 297
    )


async def test_questions_are_answered_by_the_hook_and_never_prompt(tmp_path: Path) -> None:
    handler = ScriptedHandler(PermissionDecision("deny"))
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "bypassPermissions"), handler)
    assert client.options.can_use_tool is not None
    assert client.options.hooks is not None
    hook = client.options.hooks["PreToolUse"][1].hooks[0]
    tool_input = {"questions": [{"question": "Which?", "options": [{"label": "A"}]}]}

    await hook(
        {
            "hook_event_name": "PreToolUse",
            "session_id": "sdk-1",
            "transcript_path": "/t",
            "cwd": str(tmp_path),
            "tool_name": "AskUserQuestion",
            "tool_input": tool_input,
            "tool_use_id": "toolu_q",
        },
        "toolu_q",
        {"signal": None},
    )
    result = await client.options.can_use_tool(
        "AskUserQuestion", tool_input, ToolPermissionContext(tool_use_id="toolu_q")
    )

    assert result == PermissionResultAllow(updated_input={**tool_input, "answers": {"Which?": "A"}})
    assert handler.requests == []


@pytest.mark.parametrize(
    ("decision", "message"),
    [
        (PermissionDecision("deny", "not now"), "not now"),
        (PermissionDecision("deny"), "The user denied this action."),
    ],
)
async def test_denials_carry_a_message_to_the_agent(
    tmp_path: Path, decision: PermissionDecision, message: str
) -> None:
    _, client = await Opened(tmp_path).open(
        SessionSpec(tmp_path, "default"), ScriptedHandler(decision)
    )
    assert client.options.can_use_tool is not None

    result = await client.options.can_use_tool("Edit", {}, ToolPermissionContext())

    assert result == PermissionResultDeny(message=message)


async def test_send_submits_one_user_message_with_images_and_file_paths(tmp_path: Path) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    user_input = UserInput(
        text="Look at these",
        images=(ImageInput("image/png", "aGVsbG8="),),
        file_paths=(Path("/data/a/notes.pdf"), Path("/data/b/log.txt")),
    )

    await run.send(user_input)
    await run.close()

    assert client.prompts == [
        {
            "type": "user",
            "message": {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "aGVsbG8="},
                    },
                    {
                        "type": "text",
                        "text": "Look at these\n\nAttached files:\n- /data/a/notes.pdf\n"
                        "- /data/b/log.txt",
                    },
                ],
            },
            "parent_tool_use_id": None,
        }
    ]


async def test_send_with_text_only(tmp_path: Path) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))

    await run.send(UserInput(text="hi"))
    await run.close()

    assert client.prompts[0]["message"]["content"] == [{"type": "text", "text": "hi"}]


async def test_one_reader_reports_every_turn_including_unsolicited_ones(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))
    await run.send(UserInput(text="start a background sleep"))

    client.push(
        SystemMessage(subtype="init", data={"session_id": "sdk-1"}),
        AssistantMessage(content=[TextBlock("started")], model="m"),
        RESULT,
        # Later, with no user message: the background task finished.
        AssistantMessage(content=[TextBlock("the sleep finished")], model="m"),
        RESULT,
    )
    await until(lambda: len(opened.sink.calls) == 8)
    await run.close()

    assert [name for name, _ in opened.sink.calls] == [
        "provider_session_id",
        "connectors",
        "message",
        "provider_session_id",
        "result",
        "message",
        "provider_session_id",
        "result",
    ]
    assert len(client.prompts) == 1


@pytest.mark.parametrize(
    ("ending", "error"),
    [(None, "the agent process ended"), (ProcessError("boom", exit_code=1), "boom")],
)
async def test_an_ended_stream_closes_the_run_and_reports_it(
    tmp_path: Path, ending: Exception | None, error: str
) -> None:
    opened = Opened(tmp_path)
    _, client = await opened.open(SessionSpec(tmp_path, "default"))

    client.push(ending)
    await until(lambda: bool(opened.sink.calls))

    ((name, message),) = opened.sink.calls
    assert name == "stopped"
    assert error in str(message)
    assert client.disconnects == 1


async def test_background_tasks_are_counted(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))

    client.push(
        task_started("t1"),
        task_started("t2"),
        task_started("t2"),
        TaskNotificationMessage(
            subtype="task_notification",
            data={},
            task_id="t1",
            status="completed",
            output_file="/o",
            summary="done",
            uuid="u",
            session_id="sdk-1",
        ),
        TaskUpdatedMessage(
            subtype="task_updated", data={}, task_id="t2", patch={}, status="running"
        ),
        TaskUpdatedMessage(
            subtype="task_updated", data={}, task_id="t9", patch={}, status="killed"
        ),
        TaskUpdatedMessage(
            subtype="task_updated", data={}, task_id="t2", patch={}, status="killed"
        ),
    )

    def counts() -> list[tuple[str, object]]:
        return [call for call in opened.sink.calls if call[0] == "background_tasks"]

    await until(lambda: len(counts()) == 4)
    await run.close()

    assert counts() == [
        ("background_tasks", 1),
        ("background_tasks", 2),
        ("background_tasks", 1),
        ("background_tasks", 0),
    ]


def task_started(
    task_id: str,
    tool_use_id: str | None = None,
    task_type: str | None = None,
    background: bool | None = None,
) -> TaskStartedMessage:
    return TaskStartedMessage(
        subtype="task_started",
        data={} if background is None else {"is_backgrounded": background},
        task_id=task_id,
        description="sleep 40",
        uuid="u",
        session_id="sdk-1",
        tool_use_id=tool_use_id,
        task_type=task_type,
    )


def task_updated(task_id: str, **patch: object) -> TaskUpdatedMessage:
    status = patch.get("status")
    return TaskUpdatedMessage(
        subtype="task_updated",
        data={},
        task_id=task_id,
        patch=dict(patch),
        status=status if isinstance(status, str) else None,  # pyright: ignore[reportArgumentType]
    )


def task_done(task_id: str, status: str, tool_use_id: str | None = None) -> TaskNotificationMessage:
    return TaskNotificationMessage(
        subtype="task_notification",
        data={},
        task_id=task_id,
        status=status,  # pyright: ignore[reportArgumentType]
        output_file="/o",
        summary="done",
        uuid="u",
        session_id="sdk-1",
        tool_use_id=tool_use_id,
    )


def tasks_reported(sink: RecordingSink) -> list[object]:
    return [value for name, value in sink.calls if name == "task"]


async def test_task_lifecycles_are_reported(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))

    client.push(
        task_started("t1", "toolu_1", "local_agent", background=True),
        task_started("t2", "toolu_2", "local_bash", background=False),
        task_started("t3"),
        task_updated("t2", is_backgrounded=True),
        task_updated("t2", status="running", end_time=3),
        task_updated("t3", is_backgrounded=True, status="failed"),
        task_updated("t2", status="killed"),
        task_done("t1", "completed", "toolu_1"),
        task_done("t9", "stopped"),
    )
    await until(lambda: len(tasks_reported(opened.sink)) == 9)
    await run.close()

    assert tasks_reported(opened.sink) == [
        AgentTask(
            task_id="t1",
            phase="started",
            tool_use_id="toolu_1",
            task_type="local_agent",
            description="sleep 40",
            background=True,
        ),
        AgentTask(
            task_id="t2",
            phase="started",
            tool_use_id="toolu_2",
            task_type="local_bash",
            description="sleep 40",
        ),
        AgentTask(task_id="t3", phase="started", description="sleep 40"),
        AgentTask(task_id="t2", phase="backgrounded"),
        AgentTask(task_id="t3", phase="backgrounded"),
        AgentTask(task_id="t3", phase="finished", status="failed"),
        AgentTask(task_id="t2", phase="finished", status="stopped"),
        AgentTask(task_id="t1", phase="finished", tool_use_id="toolu_1", status="completed"),
        AgentTask(task_id="t9", phase="finished", status="stopped"),
    ]


async def test_tasks_still_running_when_the_run_closes_are_stopped(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))
    client.push(task_started("t1"), task_started("t2"), task_done("t1", "completed"))
    await until(lambda: len(tasks_reported(opened.sink)) == 3)

    await run.close()

    assert tasks_reported(opened.sink)[3:] == [
        AgentTask(task_id="t2", phase="finished", status="stopped")
    ]


async def test_tasks_still_running_when_the_agent_process_ends_are_stopped(
    tmp_path: Path,
) -> None:
    opened = Opened(tmp_path)
    _, client = await opened.open(SessionSpec(tmp_path, "default"))

    client.push(task_started("t1"), None)
    await until(lambda: ("stopped", "the agent process ended") in opened.sink.calls)

    assert [name for name, _ in opened.sink.calls] == [
        "background_tasks",
        "task",
        "task",
        "stopped",
    ]
    assert tasks_reported(opened.sink)[1] == AgentTask(
        task_id="t1", phase="finished", status="stopped"
    )


async def test_controls_are_forwarded_and_close_stops_the_reader(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))

    await run.interrupt()
    await run.set_model("claude-opus-5")
    await run.set_model(None)
    await run.set_permission_mode("plan")
    await run.close()
    client.push(AssistantMessage(content=[TextBlock("too late")], model="m"))
    await asyncio.sleep(0.01)

    assert client.calls == [
        ("interrupt", None),
        ("set_model", "claude-opus-5"),
        ("set_model", None),
        ("set_permission_mode", "plan"),
    ]
    assert client.disconnects == 1
    assert opened.sink.calls == []


async def test_connector_statuses_come_from_the_live_mcp_status(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))
    client.mcp_status = {
        "mcpServers": [
            {
                "name": "claude.ai Gmail",
                "status": "connected",
                "serverInfo": {"name": "gmail", "version": "1"},
                "tools": [{"name": "search"}],
            },
            {"name": "local-db", "status": "failed", "error": "spawn ENOENT"},
        ]
    }

    statuses = await run.connector_statuses()
    await run.close()

    assert statuses == [
        McpServer("claude.ai Gmail", "connected"),
        McpServer("local-db", "failed", "spawn ENOENT"),
    ]


@pytest.mark.parametrize(
    ("plan", "result"),
    [
        (
            PlanDecision(approved=True, mode="acceptEdits"),
            PermissionResultAllow(
                updated_permissions=[
                    PermissionUpdate(type="setMode", mode="acceptEdits", destination="session")
                ]
            ),
        ),
        (PlanDecision(approved=True), PermissionResultAllow()),
        (
            PlanDecision(approved=False, message="Keep planning: add tests"),
            PermissionResultDeny(message="Keep planning: add tests"),
        ),
        (PlanDecision(approved=False), PermissionResultDeny(message="Keep planning.")),
    ],
)
async def test_plans_go_to_the_handler_as_plans(
    tmp_path: Path, plan: PlanDecision, result: object
) -> None:
    handler = ScriptedHandler(PermissionDecision("deny"), plan)
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "plan"), handler)
    assert client.options.can_use_tool is not None

    decided = await client.options.can_use_tool(
        "ExitPlanMode", {"plan": "# Plan\n1. Do it"}, ToolPermissionContext(tool_use_id="t9")
    )

    assert decided == result
    assert handler.plans == [PlanRequest("# Plan\n1. Do it", "t9")]
    assert handler.requests == []


async def test_a_plan_without_text_is_still_a_plan(tmp_path: Path) -> None:
    handler = ScriptedHandler(PermissionDecision("deny"))
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "plan"), handler)
    assert client.options.can_use_tool is not None

    await client.options.can_use_tool("ExitPlanMode", {"plan": 3}, ToolPermissionContext())

    assert handler.plans == [PlanRequest("", None)]


class StuckSink(RecordingSink):
    """Storing the command list takes a while, as the database writes can."""

    def __init__(self) -> None:
        super().__init__()
        self.inside = asyncio.Event()

    async def commands(self, catalog: CommandCatalog) -> None:
        self.inside.set()
        await asyncio.Event().wait()


class FailingSink(RecordingSink):
    async def commands(self, catalog: CommandCatalog) -> None:
        raise OSError("disk full")


async def test_a_run_whose_opening_is_cancelled_after_connecting_is_disconnected(
    tmp_path: Path,
) -> None:
    """BUG-15: otherwise the CLI process is left running, unowned."""
    opened = Opened(tmp_path)

    def described(options: ClaudeAgentOptions) -> FakeSdkClient:
        client = opened.factory(options)
        client.server_info = {"commands": [{"name": "review"}]}
        return client

    opened.provider = ClaudeProvider(tmp_path / "agent-gh", described)
    sink = StuckSink()
    spec = SessionSpec(tmp_path, "default")
    opening = asyncio.create_task(
        opened.provider.open(spec, ScriptedHandler(PermissionDecision("allow")), sink)
    )
    await asyncio.wait_for(sink.inside.wait(), 5)
    opening.cancel()
    await asyncio.gather(opening, return_exceptions=True)

    with pytest.raises(OSError, match="disk full"):
        await opened.provider.open(
            spec, ScriptedHandler(PermissionDecision("allow")), FailingSink()
        )

    assert [(c.connected, c.disconnects) for c in opened.clients] == [(True, 1), (True, 1)]


async def test_open_reports_the_commands_of_the_initialize_response(tmp_path: Path) -> None:
    opened = Opened(tmp_path)

    def described(options: ClaudeAgentOptions) -> FakeSdkClient:
        client = opened.factory(options)
        client.server_info = {"commands": [{"name": "compact", "description": "Compact"}]}
        return client

    opened.provider = ClaudeProvider(tmp_path / "agent-gh", described)

    run, _ = await opened.open(SessionSpec(tmp_path, "default"))
    await run.close()

    assert opened.sink.calls == [
        (
            "commands",
            CommandCatalog(commands=[SlashCommand(name="compact", description="Compact")]),
        )
    ]


async def test_open_reports_the_models_and_account_of_the_initialize_response(
    tmp_path: Path,
) -> None:
    opened = Opened(tmp_path)

    def described(options: ClaudeAgentOptions) -> FakeSdkClient:
        client = opened.factory(options)
        client.server_info = {
            "models": [{"value": "haiku", "displayName": "Haiku 4.5", "description": "Fast"}],
            "account": {"subscriptionType": "pro"},
        }
        return client

    opened.provider = ClaudeProvider(tmp_path / "agent-gh", described)

    run, _ = await opened.open(SessionSpec(tmp_path, "default"))
    await run.close()

    assert opened.sink.calls == [
        (
            "engine_details",
            EngineDetails(
                models=[ModelOption(value="haiku", display_name="Haiku 4.5", description="Fast")],
                account=AccountInfo(plan="Claude Pro"),
            ),
        )
    ]


async def test_context_usage_comes_from_the_engine(tmp_path: Path) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    client.context = {"percentage": 6, "totalTokens": 12994, "maxTokens": 200000}

    usage = await run.context_usage()
    client.context = {"categories": []}
    missing = await run.context_usage()
    await run.close()

    assert usage == ContextUsage(percent=6, used=12994, limit=200000)
    assert missing is None


async def test_a_message_that_fails_to_translate_does_not_end_the_run(tmp_path: Path) -> None:
    """B-05: only the CLI's own stream ending is fatal; one bad message is skipped."""
    opened = Opened(tmp_path)
    _, client = await opened.open(SessionSpec(tmp_path, "default"))

    client.push(task_done("t1", "a status the SDK does not know"), task_started("t2"))
    await until(lambda: len(tasks_reported(opened.sink)) >= 2)

    assert tasks_reported(opened.sink) == [
        AgentTask(task_id="t1", phase="finished", status="stopped"),
        AgentTask(task_id="t2", phase="started", description="sleep 40"),
    ]
    assert not any(name == "stopped" for name, _ in opened.sink.calls)


async def test_a_sink_failure_is_logged_and_the_run_keeps_reading(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    opened = Opened(tmp_path)
    _, client = await opened.open(SessionSpec(tmp_path, "default"))
    original = opened.sink.message
    failures = iter([RuntimeError("disk full")])

    async def flaky(*args: object, **kwargs: object) -> None:
        error = next(failures, None)
        if error is not None:
            raise error
        await original(*args, **kwargs)  # pyright: ignore[reportArgumentType]

    opened.sink.message = flaky  # pyright: ignore[reportAttributeAccessIssue]
    client.push(
        AssistantMessage(content=[TextBlock("first")], model="m"),
        AssistantMessage(content=[TextBlock("second")], model="m"),
    )
    await until(lambda: any(name == "message" for name, _ in opened.sink.calls))

    assert not any(name == "stopped" for name, _ in opened.sink.calls)
    assert "could not handle a message from the agent (RuntimeError: disk full)" in caplog.text


async def test_tools_and_the_write_root_reach_the_options(tmp_path: Path) -> None:
    async def noop(_args: dict[str, JsonValue]) -> str:
        return ""

    tool = AgentTool("memory_read", "Read memory", {"type": "object"}, noop)
    spec = SessionSpec(
        cwd=tmp_path,
        permission_mode="default",
        tools=(tool,),
        write_root=tmp_path / "w",
        skills=("review",),
        allowed_tools=("Bash(npm test:*)",),
        disallowed_tools=("WebFetch",),
    )

    _, client = await Opened(tmp_path).open(spec)
    allowed = await client.options.can_use_tool(  # type: ignore[misc]
        "mcp__pixie__memory_read", {}, ToolPermissionContext()
    )

    assert list(client.options.mcp_servers) == ["pixie"]  # type: ignore[arg-type]
    assert isinstance(allowed, PermissionResultAllow)
    assert client.options.hooks is not None
    assert [m.matcher for m in client.options.hooks["PreToolUse"]] == [
        "*",
        "AskUserQuestion",
        "Edit|Write|MultiEdit|NotebookEdit",
    ]
    assert client.options.skills == ["review"]
    assert client.options.allowed_tools == ["Bash(npm test:*)"]
    assert client.options.disallowed_tools == [*GIT_WRITE_RULES, "WebFetch"]


async def test_no_tools_means_no_tool_server(tmp_path: Path) -> None:
    _, client = await Opened(tmp_path).open(SessionSpec(cwd=tmp_path, permission_mode="default"))

    assert client.options.mcp_servers == {}
    assert client.options.skills is None
    assert client.options.hooks is not None
    assert len(client.options.hooks["PreToolUse"]) == 2


async def test_a_user_server_named_like_the_tool_server_is_not_auto_allowed(tmp_path: Path) -> None:
    handler = ScriptedHandler(PermissionDecision("deny", "no"))
    _, client = await Opened(tmp_path).open(
        SessionSpec(cwd=tmp_path, permission_mode="default"), handler
    )

    result = await client.options.can_use_tool(  # type: ignore[misc]
        "mcp__pixie__x", {}, ToolPermissionContext()
    )

    assert isinstance(result, PermissionResultDeny)
    assert [r.tool_name for r in handler.requests] == ["mcp__pixie__x"]
