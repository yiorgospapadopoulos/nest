"""The ACP provider against recorded OpenCode and Gemini sessions (B107)."""

import json
import os
import re
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pytest
from pydantic import JsonValue

from nestd.providers.acp import (
    INLINE_TEXT_BYTES,
    AcpLaunch,
    AcpProvider,
    AcpRun,
    AcpToolsUnsupportedError,
    probe,
)
from nestd.providers.acp_engines import (
    ANTIGRAVITY,
    GEMINI,
    GEMINI_SYSTEM_SETTINGS_ENV,
    OPENCODE,
    AcpEngine,
)
from nestd.providers.base import (
    HISTORY_CUT,
    AgentTool,
    FileInput,
    ForkPoint,
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
from nestd.providers.git_guard import DENY_REASON, WORKTREE_DENY_REASON
from nestd.providers.push_block import NO_PUSH_ENV, helpers
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

    provider = AcpProvider(engine, launcher, transport=agent)
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
    [new] = agent.requests("session/new")
    # Every run takes Nest's server for `ask_user` (B112).
    assert new["cwd"] == str(tmp_path)
    assert [s["name"] for s in new["mcpServers"]] == ["nest"]  # type: ignore[index,union-attr]
    [model] = agent.requests("session/set_config_option")
    assert (model["configId"], model["value"]) == ("model", FREE_MODEL)
    # Nest's instructions lead the first message as a block of their own.
    [prompt] = agent.requests("session/prompt")
    assert prompt["prompt"] == [
        {
            "type": "text",
            "text": "You run inside Nest.\n\nNest's tools for this chat are MCP tools: "
            "ask_user (the nest MCP server).",
        },
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


async def test_with_agents_allowed_to_push_a_pixie_run_is_not_touched(tmp_path: Path) -> None:
    """D160: no refusal, no forced `build` agent, and no git-level block."""
    agent = FakeAgent(
        load("opencode-shell-reject", tmp_path, {"git log --oneline": "git push origin main"})
    )
    run, sink, handler = await open_run(
        agent, tmp_path, guard_git=False, guard_subagents=False, permission_mode="bypassPermissions"
    )

    await turn(run, sink)

    assert outcomes(agent) == [once("once")]
    assert handler.requests == []
    env = agent.transport.launch.env
    assert "GIT_CONFIG_COUNT" not in env
    assert "OPENCODE_CONFIG_CONTENT" not in env
    await run.close()


def _text(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def _agent_rules(env: Mapping[str, str]) -> dict[str, object]:
    return json.loads(env["OPENCODE_CONFIG_CONTENT"])["agent"]


async def test_a_normal_chats_opencode_subagents_may_not_push(tmp_path: Path) -> None:
    """B127: their questions never reach Nest, so OpenCode's own rules deny their pushes,
    and the chat's own agent is left as the user set it up."""
    agent = FakeAgent(load("opencode-shell-reject", tmp_path, {}))
    run, _, _ = await open_run(agent, tmp_path, guard_git=False)

    rules = _agent_rules(agent.transport.launch.env)

    assert set(rules) == {"general", "explore"}
    for name in ("general", "explore"):
        bash = rules[name]["permission"]["bash"]  # type: ignore[index]
        assert bash["*git*push*"] == bash["*gh*pr*"] == "deny"
    await run.close()


async def test_a_guarded_runs_opencode_subagents_are_denied_pushes_too(tmp_path: Path) -> None:
    agent = FakeAgent(load("opencode-shell-reject", tmp_path, {}))
    run, _, _ = await open_run(agent, tmp_path, guard_git=True)

    rules = _agent_rules(agent.transport.launch.env)

    assert rules["build"]["permission"]["bash"] == "ask"  # type: ignore[index]
    explore = rules["explore"]["permission"]["bash"]  # type: ignore[index]
    assert (explore["*"], explore["*git*push*"]) == ("ask", "deny")
    await run.close()


async def test_a_normal_chats_gemini_subagent_is_denied_pushes_by_admin_policy(
    tmp_path: Path,
) -> None:
    """B127: Gemini's system settings name an admin policy, which outranks every other."""
    agent = FakeAgent(load("gemini-fake-key-prompt", tmp_path))
    run, _, _ = await open_run(agent, tmp_path, engine=GEMINI, guard_git=False)

    settings = json.loads(_text(agent.transport.launch.env[GEMINI_SYSTEM_SETTINGS_ENV]))
    policy = tomllib.loads(_text(settings["adminPolicyPaths"][0]))

    assert settings["security"] == {"disableAlwaysAllow": True}
    [rule] = policy["rule"]
    assert (rule["subagent"], rule["toolName"], rule["decision"]) == (
        "generalist",
        "run_shell_command",
        "deny",
    )
    pushes = re.compile(rule["commandRegex"])
    assert pushes.search("git -C x push origin main")
    assert pushes.search("gh pr create --fill")
    assert not pushes.search("git status")
    await run.close()


async def test_with_agents_allowed_to_push_gemini_keeps_its_usual_settings(
    tmp_path: Path,
) -> None:
    agent = FakeAgent(load("gemini-fake-key-prompt", tmp_path))
    run, _, _ = await open_run(
        agent, tmp_path, engine=GEMINI, guard_git=False, guard_subagents=False
    )

    assert GEMINI_SYSTEM_SETTINGS_ENV not in agent.transport.launch.env
    await run.close()


async def test_autopilot_keeps_its_worktree_refusal_when_agents_may_push(tmp_path: Path) -> None:
    agent = FakeAgent(
        load("opencode-shell-reject", tmp_path, {"git log --oneline": "git worktree remove x"})
    )
    run, sink, _ = await open_run(
        agent,
        tmp_path,
        guard_git=False,
        guard_subagents=False,
        guard_worktrees=True,
        permission_mode="bypassPermissions",
    )

    await turn(run, sink)

    assert outcomes(agent) == [once("reject")]
    [result] = [b for b in blocks(sink) if isinstance(b, ToolResultBlock)]
    assert result.content == WORKTREE_DENY_REASON
    env = agent.transport.launch.env
    assert "GIT_CONFIG_COUNT" not in env
    assert env["OPENCODE_CONFIG_CONTENT"] == OPENCODE.guarded_env["OPENCODE_CONFIG_CONTENT"]
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
    assert env["GIT_CONFIG_KEY_0"] == NO_PUSH_ENV["GIT_CONFIG_KEY_0"]
    assert env["PATH"].split(os.pathsep)[0] == str(helpers())
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


async def test_small_text_files_go_in_the_prompt_and_other_files_by_path(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    notes.write_text("# Plan\n")
    big = tmp_path / "big.log"
    big.write_text("x" * (INLINE_TEXT_BYTES + 1))
    report = tmp_path / "report.pdf"
    report.write_bytes(b"%PDF")
    agent = FakeAgent(load("opencode-method-probe", tmp_path), load("opencode-text", tmp_path))
    run, sink, _ = await open_run(agent, tmp_path, resume_id=RECORDED_SESSION)

    await run.send(
        UserInput(
            "Read these",
            files=(
                FileInput(notes, "text/markdown"),
                FileInput(big, "text/plain"),
                FileInput(report, "application/pdf"),
            ),
        )
    )
    await until(lambda: len(results(sink)) == 1)

    [prompt] = agent.requests("session/prompt")
    assert prompt["prompt"] == [
        {
            "type": "resource",
            "resource": {"uri": notes.as_uri(), "mimeType": "text/markdown", "text": "# Plan\n"},
        },
        {"type": "text", "text": f"Read these\n\nAttached files:\n- {big}\n- {report}"},
    ]
    await run.close()


async def test_a_cut_conversation_is_a_new_session_the_chat_takes_on_its_first_message(
    tmp_path: Path,
) -> None:
    """D174: ACP cannot cut a session, so a rewind or fork opens a new one; it becomes the
    chat's only when the message with the kept part goes, so a run closed before that
    opens the cut again.
    """
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, sink, _ = await open_run(
        agent, tmp_path, model=FREE_MODEL, resume_id=RECORDED_SESSION, resume_at=HISTORY_CUT
    )

    assert agent.requests("session/resume") == []
    assert [kind for kind, _ in sink.calls] == []
    await turn(run, sink, "Reply with exactly the word: pong")

    assert len(agent.requests("session/new")) == 1
    assert sink.calls[:2] == [
        ("provider_session_id", run.session_id),
        ("checkpoint", HISTORY_CUT),
    ]
    assert run.session_id != RECORDED_SESSION
    provider = AcpProvider(OPENCODE, launcher=None, transport=agent)  # type: ignore[arg-type]
    assert await provider.fork_point(tmp_path, run.session_id, HISTORY_CUT) == ForkPoint(
        HISTORY_CUT
    )
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


@pytest.mark.parametrize(
    ("listed", "name"),
    [
        ("Counting directory entries", "Counting directory entries"),
        ("New session - 2026-11-05T18:06:05.951Z", None),
    ],
)
async def test_a_chats_name_is_the_engines_title_not_its_placeholder(
    tmp_path: Path, listed: str, name: str | None
) -> None:
    agent = FakeAgent(load("opencode-text", tmp_path))
    agent.script(
        "session/list",
        [
            Step(
                "answer",
                {
                    "result": {
                        "sessions": [
                            {"sessionId": "another", "title": "Not this chat"},
                            {"sessionId": RECORDED_TEXT_SESSION, "title": listed},
                        ]
                    }
                },
            )
        ],
    )
    run, _, _ = await open_run(agent, tmp_path)

    assert run.names_chats
    assert await run.engine_title(RECORDED_TEXT_SESSION) == name
    assert agent.requests("session/list")[0]["cwd"] == str(tmp_path)
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


async def test_antigravity_sessions_carry_its_settings_and_instructions(tmp_path: Path) -> None:
    """B153: its server reads no instruction file and its subagents run unasked, so each
    session opens with them switched off and the project's instructions given."""
    (tmp_path / "AGENTS.md").write_text("Use tabs.\n")
    agent = FakeAgent(load("opencode-text", tmp_path))
    run, _, _ = await open_run(agent, tmp_path, engine=ANTIGRAVITY)

    [opened] = agent.requests("session/new")
    meta = opened["_meta"]["antigravity"]  # type: ignore[index]
    assert meta["disabledTools"] == ["invoke_subagent", "run_workflow"]  # type: ignore[index]
    assert meta["systemPrompt"]["append"] == (  # type: ignore[index]
        f"Contents of {tmp_path / 'AGENTS.md'}:\n\nUse tabs."
    )
    await run.close()


async def test_a_reopened_session_saved_in_yolo_goes_back_to_default(tmp_path: Path) -> None:
    """B153: Antigravity restores a loaded session's mode, which may run everything unasked."""
    agent = FakeAgent(load("opencode-load-after-restart", tmp_path))
    initialize = agent.exchanges["initialize"][0][-1].msg["result"]
    capabilities = {**initialize["agentCapabilities"], "sessionCapabilities": {}}  # type: ignore[index]
    agent.answer_with("initialize", {**initialize, "agentCapabilities": capabilities})  # type: ignore[dict-item]
    modes: list[JsonValue] = [{"id": m, "name": m} for m in ("default", "auto_edit", "yolo")]
    loaded: dict[str, JsonValue] = {"modes": {"currentModeId": "yolo", "availableModes": modes}}
    agent.answer_with("session/load", loaded)
    agent.answer_with("session/set_mode", {})
    run, sink, _ = await open_run(agent, tmp_path, engine=ANTIGRAVITY, resume_id=RECORDED_SESSION)

    await turn(run, sink)

    assert agent.requests("session/load")[0]["_meta"]  # sent again on a reopened session
    assert [r["modeId"] for r in agent.requests("session/set_mode")] == ["default"]
    methods = agent.methods()
    assert methods.index("session/set_mode") < methods.index("session/prompt")
    await run.close()
