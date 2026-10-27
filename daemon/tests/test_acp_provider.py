"""The ACP provider against recorded OpenCode and Gemini sessions (B107)."""

from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue

from nestd.providers.acp import AcpLaunch, AcpProvider, AcpRun, AcpToolsUnsupportedError, probe
from nestd.providers.acp_engines import GEMINI, OPENCODE, AcpEngine
from nestd.providers.base import (
    AgentTool,
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    QuestionAnswer,
    QuestionRequest,
    ResultInfo,
    RunAccount,
    SessionSpec,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserInput,
)
from nestd.providers.git_guard import DENY_REASON
from tests.acp_support import FakeAgent, Step, load
from tests.async_support import until
from tests.recording_sink import RecordingSink

FREE_MODEL = "opencode/nemotron-3.5-lightning-free"
RECORDED_SESSION = "ses_e85591b6fffetmZypZXnMQJzIa"
RECORDED_TEXT_SESSION = "ses_e8559c2fbffeMG37VUaTxc32MU"


class Handler:
    def __init__(self, *decisions: PermissionDecision) -> None:
        self.requests: list[PermissionRequest] = []
        self._decisions = list(decisions)

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return self._decisions.pop(0) if self._decisions else PermissionDecision("allow")

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        raise AssertionError

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        raise AssertionError


def spec(cwd: Path, **fields: object) -> SessionSpec:
    values: dict[str, object] = {"cwd": cwd, "permission_mode": "default", "guard_git": False}
    values.update(fields)
    return SessionSpec(**values)  # type: ignore[arg-type]


async def open_run(
    agent: FakeAgent,
    cwd: Path,
    handler: Handler | None = None,
    engine: AcpEngine = OPENCODE,
    **fields: object,
) -> tuple[AcpRun, RecordingSink, Handler]:
    sink = RecordingSink()
    handler = handler or Handler()

    async def launcher(account: RunAccount | None) -> AcpLaunch:
        return AcpLaunch(("/engines/opencode", "acp"), {"PATH": "/engine/bin", "HOME": "/home"})

    provider = AcpProvider(engine, launcher, cwd / "gh", transport=agent)
    run = await provider.open(spec(cwd, **fields), handler, sink)
    return run, sink, handler


async def turn(run: AcpRun, sink: RecordingSink, words: str = "hi") -> ResultInfo:
    before = len(results(sink))
    await run.send(UserInput(words))
    await until(lambda: len(results(sink)) > before)
    return results(sink)[-1]


def results(sink: RecordingSink) -> list[ResultInfo]:
    return [info for kind, info in sink.calls if kind == "result"]  # type: ignore[misc]


def blocks(sink: RecordingSink) -> list[object]:
    found: list[object] = []
    for kind, value in sink.calls:
        if kind == "message":
            message, _parent = cast("tuple[list[object], str | None]", value)
            found += message
    return found


def outcomes(agent: FakeAgent) -> list[JsonValue]:
    answers = agent.answered("session/request_permission")
    return [answer.get("result") for answer in answers]


def once(option: str) -> JsonValue:
    return {"outcome": {"outcome": "selected", "optionId": option}}


async def test_a_text_reply_streams_and_ends_with_its_tokens(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, sink, _ = await open_run(
        agent, tmp_path, model=FREE_MODEL, system_prompt_append="You run inside Nest."
    )

    info = await turn(run, sink, "Reply with exactly the word: pong")

    [init] = agent.requests("initialize")
    assert init["clientCapabilities"] == {
        "fs": {"readTextFile": True, "writeTextFile": True},
        "terminal": False,
    }
    assert agent.requests("session/new") == [{"cwd": str(tmp_path), "mcpServers": []}]
    [model] = agent.requests("session/set_config_option")
    assert (model["configId"], model["value"]) == ("model", FREE_MODEL)
    # Nest's instructions lead the first message as a block of their own.
    [prompt] = agent.requests("session/prompt")
    assert prompt["prompt"] == [
        {"type": "text", "text": "You run inside Nest."},
        {"type": "text", "text": "Reply with exactly the word: pong"},
    ]
    assert ("provider_session_id", "ses_e8559c2fbffeMG37VUaTxc32MU") in sink.calls
    assert "".join(str(v) for k, v in sink.calls if k == "text_delta") == "pong"
    assert [b for b in blocks(sink) if isinstance(b, TextBlock)] == [TextBlock(text="pong")]
    assert any(isinstance(b, ThinkingBlock) and "pong" in b.text for b in blocks(sink))
    assert (info.is_error, info.subtype) == (False, "success")
    assert (info.tokens.input_tokens, info.tokens.output_tokens) == (12497, 4 + 81)
    context = await run.context_usage()
    assert context is not None
    assert (context.used, context.limit) == (12497, 262144)
    commands = [c for k, c in sink.calls if k == "commands"]
    assert [c.name for c in commands[-1].commands] == ["customize-opencode", "init", "review"]  # type: ignore[attr-defined]
    await run.close()
    assert agent.transport.closed


async def test_an_edit_shows_its_diff_and_nest_writes_the_file(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello\n")
    agent = FakeAgent(load("opencode-edit", tmp_path))
    run, sink, handler = await open_run(agent, tmp_path)

    await turn(run, sink)

    [asked] = handler.requests
    assert asked.tool_name == "Edit"
    assert asked.tool_input["file_path"] == str(notes)
    edit = next(b for b in blocks(sink) if isinstance(b, ToolUseBlock) and b.name == "Edit")
    assert edit.input == {
        "file_path": str(notes),
        "old_string": "hello",
        "new_string": "hello world",
    }
    assert outcomes(agent) == [once("once")]
    assert notes.read_text() == "hello world\n"
    result = next(
        b for b in blocks(sink) if isinstance(b, ToolResultBlock) and b.tool_use_id == edit.id
    )
    assert not result.is_error
    await run.close()


async def test_an_edit_outside_the_write_root_is_rejected_and_not_written(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    notes.write_text("hello\n")
    agent = FakeAgent(load("opencode-edit", tmp_path))
    run, sink, handler = await open_run(agent, tmp_path, write_root=tmp_path / "pixie")

    await turn(run, sink)

    assert handler.requests == []
    assert outcomes(agent) == [once("reject")]
    # The recorded engine still sends the write; Nest refuses it.
    [write] = agent.answered("fs/write_text_file")
    assert "error" in write
    assert notes.read_text() == "hello\n"
    await run.close()


async def test_a_rejected_command_answers_reject_once(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-shell-reject", tmp_path))
    run, sink, handler = await open_run(
        agent, tmp_path, handler=Handler(PermissionDecision("deny"))
    )

    await turn(run, sink)

    [asked] = handler.requests
    assert (asked.tool_name, asked.tool_input) == ("Bash", {"command": "git log --oneline"})
    assert asked.always_rule == "Bash(git log --oneline)"
    assert outcomes(agent) == [once("reject")]
    [result] = [b for b in blocks(sink) if isinstance(b, ToolResultBlock)]
    assert result.is_error
    await run.close()


@pytest.mark.parametrize("mode", ["default", "bypassPermissions"])
async def test_a_guarded_runs_push_is_rejected_without_asking(tmp_path: Path, mode: str) -> None:
    agent = FakeAgent(
        load("opencode-shell-reject", tmp_path, {"git log --oneline": "git push origin main"})
    )
    run, sink, handler = await open_run(
        agent, tmp_path, guard_git=True, permission_mode=mode, env={"PORT": "4100"}
    )

    await turn(run, sink)

    assert handler.requests == []
    assert outcomes(agent) == [once("reject")]
    # The transcript says why, though the engine only hears "rejected".
    [result] = [b for b in blocks(sink) if isinstance(b, ToolResultBlock)]
    assert (result.content, result.is_error) == (DENY_REASON, True)
    env = agent.transport.launch.env
    assert (env["GH_TOKEN"], env["GIT_TERMINAL_PROMPT"]) == ("", "0")
    # OpenCode's own agent settings cannot loosen a guarded run's rules.
    assert env["OPENCODE_CONFIG_CONTENT"] == OPENCODE.guarded_env["OPENCODE_CONFIG_CONTENT"]
    assert env["PORT"] == "4100"
    assert agent.transport.cwd == tmp_path
    await run.close()


def mcp_turn(title: str, end: str) -> list[Step]:
    """An MCP tool call as OpenCode makes it (live, B107): asked about before its input is
    known, then run with the input, or failed when rejected.
    """
    call: dict[str, JsonValue] = {"toolCallId": "call-1", "title": title, "kind": "other"}
    ask: dict[str, JsonValue] = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "session/request_permission",
        "params": {
            "sessionId": RECORDED_TEXT_SESSION,
            "toolCall": {**call, "status": "pending", "locations": [], "rawInput": {}},
            "options": [
                {"optionId": "once", "kind": "allow_once"},
                {"optionId": "always", "kind": "allow_always"},
                {"optionId": "reject", "kind": "reject_once"},
            ],
        },
    }
    ended: dict[str, JsonValue] = {"sessionUpdate": "tool_call_update", **call, "status": end}
    if end == "completed":
        ended["rawInput"] = {"text": "hi"}
        ended["content"] = [{"type": "content", "content": {"type": "text", "text": "done"}}]
    else:
        ended["rawOutput"] = {
            "error": "The user rejected permission to use this specific tool call."
        }
    return [
        Step(
            "push",
            update({"sessionUpdate": "tool_call", "status": "pending", "rawInput": {}, **call}),
        ),
        Step("ask", ask),
        Step("push", update(ended)),
        Step("answer", {"result": {"stopReason": "end_turn"}}),
    ]


@pytest.mark.parametrize("title", ["nest_artifact_list", "nest_artifact_list(kind: page)"])
async def test_nests_own_mcp_tools_are_allowed_without_asking(tmp_path: Path, title: str) -> None:
    async def listing(_input: dict[str, JsonValue]) -> str:
        return "none"

    tool = AgentTool("artifact_list", "Lists artifacts", {"type": "object"}, listing)
    agent = FakeAgent(load("opencode-text", tmp_path))
    agent.script("session/prompt", mcp_turn(title, "completed"))
    run, sink, handler = await open_run(agent, tmp_path, guard_git=True, nest_tools=(tool,))

    await turn(run, sink)

    assert handler.requests == []
    assert outcomes(agent) == [once("once")]
    [use] = [b for b in blocks(sink) if isinstance(b, ToolUseBlock)]
    # Drawn once it runs, with the input the engine gives only then.
    assert (use.name, use.input) == ("mcp__nest__artifact_list", {"text": "hi"})
    [server] = agent.requests("session/new")[0]["mcpServers"]  # type: ignore[misc]
    assert (server["type"], server["name"]) == ("http", "nest")  # type: ignore[index]
    assert server["headers"][0]["value"].startswith("Bearer ")  # type: ignore[index]
    await run.close()


@pytest.mark.parametrize("title", ["github_create_pull_request", "terminal_run_command"])
async def test_a_guarded_runs_risky_mcp_tool_is_rejected_without_asking(
    tmp_path: Path, title: str
) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    agent.script("session/prompt", mcp_turn(title, "failed"))
    run, sink, handler = await open_run(
        agent, tmp_path, guard_git=True, permission_mode="bypassPermissions"
    )

    await turn(run, sink)

    assert handler.requests == []
    assert outcomes(agent) == [once("reject")]
    [result] = [b for b in blocks(sink) if isinstance(b, ToolResultBlock)]
    assert (result.content, result.is_error) == (DENY_REASON, True)
    await run.close()


PUSH = "git push origin main 2>&1"


@pytest.mark.parametrize("announced", [None, "execute"])
async def test_a_rejected_command_without_its_kind_is_drawn_as_bash(
    tmp_path: Path, announced: str | None
) -> None:
    """OpenCode 1.19.4 asked about a pixie's push with no kind (or a vaguer one than its
    call's), and the transcript showed the command's title as the tool's name.
    """
    raw: dict[str, JsonValue] = {"cwd": str(tmp_path), "command": PUSH, "directories": []}
    asked: dict[str, JsonValue] = {"toolCallId": "call-9", "title": PUSH, "rawInput": raw}
    steps: list[Step] = []
    if announced is not None:
        steps.append(
            Step(
                "push",
                update(
                    {
                        "sessionUpdate": "tool_call",
                        "toolCallId": "call-9",
                        "title": "bash",
                        "kind": announced,
                        "status": "pending",
                        "rawInput": {},
                    }
                ),
            )
        )
        asked["kind"] = "other"
    steps += [
        Step(
            "ask",
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "session/request_permission",
                "params": {
                    "sessionId": RECORDED_TEXT_SESSION,
                    "toolCall": asked,
                    "options": [
                        {"optionId": "once", "kind": "allow_once"},
                        {"optionId": "reject", "kind": "reject_once"},
                    ],
                },
            },
        ),
        Step(
            "push",
            update(
                {"sessionUpdate": "tool_call_update", "toolCallId": "call-9", "status": "failed"}
            ),
        ),
        Step("answer", {"result": {"stopReason": "end_turn"}}),
    ]
    agent = FakeAgent(load("opencode-text", tmp_path))
    agent.script("session/prompt", steps)
    run, sink, handler = await open_run(
        agent, tmp_path, guard_git=True, permission_mode="bypassPermissions"
    )

    await turn(run, sink)

    assert handler.requests == []
    assert outcomes(agent) == [once("reject")]
    [use] = [b for b in blocks(sink) if isinstance(b, ToolUseBlock)]
    assert (use.name, use.input) == ("Bash", {"command": PUSH})
    [result] = [b for b in blocks(sink) if isinstance(b, ToolResultBlock)]
    assert result.content == DENY_REASON
    await run.close()


async def test_the_users_own_mcp_tool_is_asked_in_default_mode(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    agent.script("session/prompt", mcp_turn("echo_echo", "completed"))
    run, sink, handler = await open_run(agent, tmp_path)

    await turn(run, sink)

    [asked] = handler.requests
    assert asked.tool_name == "echo_echo"
    assert outcomes(agent) == [once("once")]
    await run.close()


async def test_nest_tools_need_an_engine_with_http_mcp(tmp_path: Path) -> None:
    async def listing(_input: dict[str, JsonValue]) -> str:
        return "none"

    agent = FakeAgent(load("opencode-text", tmp_path))
    agent.answer_with("initialize", {"protocolVersion": 1, "agentCapabilities": {}})
    tool = AgentTool("artifact_list", "Lists artifacts", {"type": "object"}, listing)

    with pytest.raises(AcpToolsUnsupportedError):
        await open_run(agent, tmp_path, nest_tools=(tool,))
    assert agent.transport.closed


async def test_always_allow_is_kept_by_nest_and_answered_once(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-shell-allow", tmp_path))
    handler = Handler(PermissionDecision("allow", always=True))
    run, sink, _ = await open_run(agent, tmp_path, handler=handler)

    await turn(run, sink)
    await turn(run, sink)

    assert len(handler.requests) == 1
    assert outcomes(agent) == [once("once"), once("once")]
    await run.close()


async def test_resume_uses_session_resume_when_the_engine_has_it(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-method-probe", tmp_path), load("opencode-text", tmp_path))
    run, sink, _ = await open_run(agent, tmp_path, resume_id=RECORDED_SESSION)

    await turn(run, sink, "And now?")

    assert "session/load" not in agent.methods()
    assert agent.requests("session/resume")[0]["sessionId"] == RECORDED_SESSION
    # No leading instructions for a reopened chat.
    [prompt] = agent.requests("session/prompt")
    assert prompt["prompt"] == [{"type": "text", "text": "And now?"}]
    assert ("provider_session_id", RECORDED_SESSION) in sink.calls
    await run.close()


async def test_a_loaded_sessions_replay_is_dropped(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-load-after-restart", tmp_path))
    initialize = agent.exchanges["initialize"][0][-1].msg["result"]
    capabilities = {**initialize["agentCapabilities"], "sessionCapabilities": {}}  # type: ignore[index]
    agent.answer_with("initialize", {**initialize, "agentCapabilities": capabilities})  # type: ignore[dict-item]
    run, sink, _ = await open_run(agent, tmp_path, resume_id=RECORDED_SESSION)

    assert "session/load" in agent.methods()
    assert blocks(sink) == []
    assert not any(kind in ("text_delta", "thinking_delta") for kind, _ in sink.calls)

    await turn(run, sink)

    [text] = [b for b in blocks(sink) if isinstance(b, TextBlock)]
    assert text.text.startswith('I replaced the single word "hello"')
    await run.close()


async def test_stop_cancels_the_turn(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-cancel", tmp_path))
    run, sink, _ = await open_run(agent, tmp_path)

    await run.send(UserInput("Write an essay."))
    await until(lambda: any(kind == "text_delta" for kind, _ in sink.calls))
    await run.interrupt()
    await until(lambda: bool(results(sink)))

    [info] = results(sink)
    assert (info.is_error, info.subtype) == (False, "cancelled")
    assert agent.requests("session/cancel")
    # What was written before the Stop stays in the transcript.
    assert any(isinstance(b, TextBlock) and b.text.startswith("Git") for b in blocks(sink))
    await run.close()


async def test_a_prompt_error_ends_the_turn_and_the_run_goes_on(tmp_path: Path) -> None:
    agent = FakeAgent(load("gemini-fake-key-prompt", tmp_path))
    run, sink, _ = await open_run(agent, tmp_path, engine=GEMINI, model="gemini-3.5-flash-lite")

    first = await turn(run, sink)
    second = await turn(run, sink)

    assert agent.requests("session/set_model")[0]["modelId"] == "gemini-3.5-flash-lite"
    for info in (first, second):
        assert info.is_error
        assert info.errors == ["API key not valid. Please pass a valid API key."]
    assert not any(kind == "stopped" for kind, _ in sink.calls)
    await run.close()


async def test_the_engine_ending_stops_the_run(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, sink, _ = await open_run(agent, tmp_path)

    agent.transport.end()
    await until(lambda: any(kind == "stopped" for kind, _ in sink.calls))

    assert ("stopped", "OpenCode ended") in sink.calls
    await run.close()


async def test_probe_reads_the_models_and_closes_the_session(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-method-probe", tmp_path), load("opencode-text", tmp_path))

    found = await probe(AcpLaunch(("opencode", "acp"), {}), tmp_path, agent)

    assert (found.signed_in, found.mcp_http) == (True, True)
    assert found.agent_version == "1.18.26"
    assert found.models[0].value == "default"
    assert found.models[0].resolved_model == "opencode/big-pickle"
    assert FREE_MODEL in [m.value for m in found.models]
    assert agent.methods() == ["initialize", "session/new", "session/close"]


async def test_probe_says_when_the_engine_needs_a_sign_in(tmp_path: Path) -> None:
    agent = FakeAgent(load("gemini-handshake-unauthenticated", tmp_path))

    found = await probe(AcpLaunch(("gemini", "--acp"), {}), tmp_path, agent)

    assert found.signed_in is False
    assert found.models == []


def update(fields: dict[str, JsonValue]) -> dict[str, JsonValue]:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {"sessionId": RECORDED_TEXT_SESSION, "update": fields},
    }
