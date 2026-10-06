import asyncio
from pathlib import Path

import pytest
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    PermissionResultAllow,
    PermissionResultDeny,
    ProcessError,
    ResultMessage,
    SystemMessage,
    TaskNotificationMessage,
    TaskStartedMessage,
    TaskUpdatedMessage,
    TextBlock,
    ToolPermissionContext,
)

from harness.providers.base import (
    ImageInput,
    McpServer,
    PermissionDecision,
    PermissionRequest,
    QuestionAnswer,
    QuestionRequest,
    SessionSpec,
    UserInput,
)
from harness.providers.claude import ClaudeProvider, ClaudeRun
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


class ScriptedHandler:
    def __init__(self, decision: PermissionDecision) -> None:
        self.decision = decision
        self.requests: list[PermissionRequest] = []

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return self.decision

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        return QuestionAnswer({"Which?": "A"})


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
    assert options.disallowed_tools == list(GIT_WRITE_RULES)
    assert options.hooks is not None
    git_matcher, question_matcher = options.hooks["PreToolUse"]
    assert git_matcher.matcher == "Bash"
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
    }


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
    await until(lambda: len(opened.sink.calls) == 4)
    await run.close()

    assert opened.sink.calls == [
        ("background_tasks", 1),
        ("background_tasks", 2),
        ("background_tasks", 1),
        ("background_tasks", 0),
    ]


def task_started(task_id: str) -> TaskStartedMessage:
    return TaskStartedMessage(
        subtype="task_started",
        data={},
        task_id=task_id,
        description="sleep 40",
        uuid="u",
        session_id="sdk-1",
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
