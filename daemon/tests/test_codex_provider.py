import asyncio
from collections.abc import Mapping
from pathlib import Path

import pytest

from nestd.config.models import PermissionMode
from nestd.providers.base import (
    ImageInput,
    McpServer,
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    QuestionAnswer,
    QuestionRequest,
    ResultInfo,
    SessionSpec,
    TextBlock,
    UserInput,
)
from nestd.providers.claude import agent_env
from nestd.providers.codex import (
    CODEX_UNSUPPORTED,
    NO_REWIND,
    CodexNotSignedInError,
    CodexProvider,
    CodexRun,
)
from nestd.providers.codex_engine import NOT_SIGNED_IN
from nestd.providers.codex_process import CODEX_HOME_ENV, CodexBinary
from nestd.providers.codex_rpc import CodexClosedError, CodexRpcError
from tests.async_support import until
from tests.codex_support import SIGNED_OUT, FakeAppServer, item, note, turn_completed
from tests.recording_sink import RecordingSink


class Handler:
    def __init__(self) -> None:
        self.requests: list[PermissionRequest] = []

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return PermissionDecision("allow")

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        raise AssertionError

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        raise AssertionError


async def shell_env() -> Mapping[str, str]:
    return {"PATH": "/opt/homebrew/bin:/usr/bin", "NVM_DIR": "/Users/me/.nvm"}


def provider(tmp_path: Path, server: FakeAppServer) -> CodexProvider:
    return CodexProvider(
        tmp_path / "gh",
        codex_home=tmp_path / "codex-home",
        transport=server,
        shell_env=shell_env,
        binary=CodexBinary(tmp_path / "codex"),
        base_env={"HOME": "/Users/me", "PATH": "/usr/bin"},
    )


def spec(tmp_path: Path, **fields: object) -> SessionSpec:
    values: dict[str, object] = {"cwd": tmp_path, "permission_mode": "default", "guard_git": False}
    values.update(fields)
    return SessionSpec(**values)  # type: ignore[arg-type]


async def opened(
    tmp_path: Path, **fields: object
) -> tuple[FakeAppServer, CodexRun, RecordingSink, Handler]:
    server = FakeAppServer()
    sink = RecordingSink()
    handler = Handler()
    run = await provider(tmp_path, server).open(spec(tmp_path, **fields), handler, sink)
    return server, run, sink, handler


async def test_opening_starts_app_server_and_a_thread_in_the_chats_folder(
    tmp_path: Path,
) -> None:
    server, run, sink, _ = await opened(
        tmp_path, model="default", system_prompt_append="You are running inside Nest."
    )

    [launch] = server.launches
    assert launch.args == (str(tmp_path / "codex"), "app-server", "--listen", "stdio://")
    assert launch.cwd == tmp_path
    assert launch.env[CODEX_HOME_ENV] == str(tmp_path / "codex-home")
    assert launch.env["HOME"] == "/Users/me"
    assert launch.env["NVM_DIR"] == "/Users/me/.nvm"
    assert "GH_TOKEN" not in launch.env
    assert [m.get("method") for m in server.sent] == [
        "initialize",
        "initialized",
        "account/read",
        "thread/start",
    ]
    assert server.requests("thread/start") == [
        {
            "cwd": str(tmp_path),
            "approvalPolicy": "untrusted",
            "approvalsReviewer": "user",
            "sandbox": "workspace-write",
            "config": {},
            "developerInstructions": "You are running inside Nest.",
        }
    ]
    assert sink.calls == [("provider_session_id", "thread-1")]
    assert run.steers
    await run.close()
    assert server.transport.closed


async def test_a_guarded_run_has_no_git_credentials_in_codex_or_its_commands(
    tmp_path: Path,
) -> None:
    server, run, _, _ = await opened(tmp_path, guard_git=True, model="gpt-5.5")

    env = server.launches[0].env
    assert env["GH_TOKEN"] == ""
    assert env["GIT_CONFIG_VALUE_0"] == ""
    assert env["GH_CONFIG_DIR"] == str(tmp_path / "gh")
    [start] = server.requests("thread/start")
    assert start["model"] == "gpt-5.5"
    assert start["config"] == {"shell_environment_policy.set": {**_agent_env(tmp_path)}}
    assert "developerInstructions" not in start
    await run.close()


def _agent_env(tmp_path: Path) -> dict[str, str]:
    return agent_env(tmp_path / "gh")


async def test_a_session_with_a_thread_resumes_it(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(tmp_path, resume_id="thread-7")

    [resume] = server.requests("thread/resume")
    assert resume["threadId"] == "thread-7"
    assert resume["cwd"] == str(tmp_path)
    assert sink.calls == [("provider_session_id", "thread-7")]
    await run.close()


async def test_opening_without_a_login_fails_with_the_sign_in_message(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.answers["account/read"] = SIGNED_OUT

    with pytest.raises(CodexNotSignedInError) as raised:
        await provider(tmp_path, server).open(spec(tmp_path), Handler(), RecordingSink())

    assert str(raised.value) == NOT_SIGNED_IN
    assert raised.value.payload() == {"detail": NOT_SIGNED_IN, "code": "codex_not_signed_in"}
    assert server.requests("thread/start") == []
    assert server.transport.closed


async def test_a_thread_without_an_id_fails_the_open(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.answers["thread/start"] = {"thread": {}}
    sink = RecordingSink()

    with pytest.raises(RuntimeError, match="no thread"):
        await provider(tmp_path, server).open(spec(tmp_path), Handler(), sink)

    assert server.transport.closed
    assert sink.calls == []


async def test_the_default_binary_is_the_bundled_one(tmp_path: Path) -> None:
    server = FakeAppServer()
    codex = CodexProvider(tmp_path / "gh", transport=server)

    run = await codex.open(spec(tmp_path), Handler(), RecordingSink())

    assert Path(server.launches[0].args[0]).name in {"codex", "codex.exe"}
    await run.close()


async def test_a_message_starts_a_turn_with_the_runs_settings(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(tmp_path, effort="high", extra_dirs=(tmp_path / "att",))
    server.script(
        note("turn/started", threadId="thread-1", turn={"id": "turn-1"}),
        item("completed", {"type": "agentMessage", "id": "a1", "text": "Done"}),
        turn_completed(),
    )

    await run.send(
        UserInput(
            "Look at this",
            images=(ImageInput("image/png", "QUJD"),),
            file_paths=(tmp_path / "att" / "notes.txt",),
        )
    )
    await until(lambda: any(kind == "result" for kind, _ in sink.calls))

    [turn] = server.requests("turn/start")
    assert turn == {
        "threadId": "thread-1",
        "input": [
            {"type": "image", "url": "data:image/png;base64,QUJD"},
            {
                "type": "text",
                "text": f"Look at this\n\nAttached files:\n- {tmp_path / 'att' / 'notes.txt'}",
                "text_elements": [],
            },
        ],
        "approvalPolicy": "untrusted",
        "approvalsReviewer": "user",
        "sandboxPolicy": {
            "type": "workspaceWrite",
            "writableRoots": [str(tmp_path / "att")],
            "networkAccess": True,
            "excludeTmpdirEnvVar": False,
            "excludeSlashTmp": False,
        },
        "effort": "high",
    }
    assert ("message", ([TextBlock(text="Done")], None)) in sink.calls
    _, result = sink.calls[-1]
    assert isinstance(result, ResultInfo)
    assert result.subtype == "success"
    await run.close()


async def test_a_new_model_and_mode_apply_from_the_next_turn(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path)
    mode: PermissionMode = "bypassPermissions"

    await run.set_model("gpt-5.5")
    await run.set_permission_mode(mode)
    await run.send(UserInput("go"))
    await run.set_model("default")
    await run.send(UserInput("again"))

    first, second = server.requests("turn/start")
    assert (first["model"], first["approvalPolicy"], first["sandboxPolicy"]) == (
        "gpt-5.5",
        "never",
        {"type": "dangerFullAccess"},
    )
    assert "model" not in second
    await run.close()


async def test_a_turn_id_from_turn_started_is_kept_over_the_answers(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path)
    server.answers["turn/start"] = {"turn": {}}

    await run.send(UserInput("go"))
    assert run.stream.turn_id is None

    server.answers["turn/start"] = {"turn": {"id": "turn-late"}}
    run.stream.turn_id = "turn-early"
    await run.send(UserInput("go"))
    assert run.stream.turn_id == "turn-early"
    await run.close()


async def test_a_message_written_into_the_turn_is_steered_and_taken_on_its_echo(
    tmp_path: Path,
) -> None:
    server, run, sink, _ = await opened(tmp_path)
    run.stream.turn_id = "turn-1"
    server.steer_turns.append(
        [item("started", {"type": "userMessage", "id": "u2", "clientId": "q1", "content": []})]
    )

    await run.steer(UserInput("also this"), "q1")
    await until(lambda: ("message_taken", ("q1", "u2")) in sink.calls)

    [steer] = server.requests("turn/steer")
    assert steer["expectedTurnId"] == "turn-1"
    assert steer["clientUserMessageId"] == "q1"
    assert steer["input"] == [{"type": "text", "text": "also this", "text_elements": []}]
    assert await run.withdraw("q1")
    await run.close()


async def test_a_steered_message_codex_has_cannot_be_taken_back_until_the_turn_ends(
    tmp_path: Path,
) -> None:
    server, run, _, _ = await opened(tmp_path)
    run.stream.turn_id = "turn-1"

    await run.steer(UserInput("wait"), "q1")

    assert not await run.withdraw("q1")
    server.notify("turn/completed", turn_completed("interrupted")["params"])  # type: ignore[arg-type]
    await until(lambda: run.stream.turn_id is None)
    assert await run.withdraw("q1")
    assert run.stream.steered == set()
    await run.close()


async def test_steering_without_a_turn_or_refused_leaves_the_message_with_nest(
    tmp_path: Path,
) -> None:
    server, run, _, _ = await opened(tmp_path)

    with pytest.raises(RuntimeError, match="no turn"):
        await run.steer(UserInput("x"), "q1")

    run.stream.turn_id = "turn-1"
    server.errors["turn/steer"] = (-32600, "turn mismatch")
    with pytest.raises(CodexRpcError, match="turn mismatch"):
        await run.steer(UserInput("x"), "q1")
    assert run.stream.steered == set()
    await run.close()


async def test_interrupt_stops_the_running_turn_only(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path)

    await run.interrupt()
    run.stream.turn_id = "turn-1"
    await run.interrupt()

    assert server.requests("turn/interrupt") == [{"threadId": "thread-1", "turnId": "turn-1"}]
    await run.close()


async def test_connector_statuses_come_from_codexs_mcp_list(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path)
    server.answers["mcpServerStatus/list"] = {
        "data": [
            {"name": "github", "runtimeStatus": "connected", "toolsError": None},
            {"name": "linear", "runtimeStatus": "authenticationRequired"},
            {"name": "db", "runtimeStatus": None, "toolsError": "no tools"},
            {"name": ""},
        ]
    }

    servers = await run.connector_statuses()

    assert servers == [
        McpServer("github", "connected"),
        McpServer("linear", "needs-auth"),
        McpServer("db", "pending", "no tools"),
    ]
    assert server.requests("mcpServerStatus/list") == [
        {"threadId": "thread-1", "detail": "toolsAndAuthOnly"}
    ]
    await run.close()


async def test_claude_only_operations_fail_cleanly(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path)
    codex = provider(tmp_path, server)

    rewind = await run.rewind_files("cp-1", dry_run=True)

    assert (rewind.can_rewind, rewind.error) == (False, NO_REWIND)
    assert not await run.stop_task("task-1")
    assert await run.context_usage() is None
    assert await codex.fork_point(tmp_path, "thread-1", "m1") is None
    assert {"rewind", "fork", "slash_commands", "plan_review", "task_list"} <= CODEX_UNSUPPORTED
    # Stage 2: pixies, the pixies a chat calls and Nest's tools run on Codex too.
    assert CODEX_UNSUPPORTED.isdisjoint({"pixies", "subagents", "nest_tools"})
    assert codex.unsupported == CODEX_UNSUPPORTED
    await run.close()


async def test_codex_ending_on_its_own_stops_the_run(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(tmp_path)
    server.stderr = "crashed"

    server.transport.end()

    await until(lambda: any(kind == "stopped" for kind, _ in sink.calls))
    assert sink.calls[-1] == ("stopped", "Codex ended: crashed")
    await run.close()


async def test_codex_ending_while_the_run_opens_fails_the_open_only(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.silent.add("account/read")
    sink = RecordingSink()
    opening = asyncio.create_task(provider(tmp_path, server).open(spec(tmp_path), Handler(), sink))
    await until(lambda: bool(server.requests("account/read")))

    server.transport.end()

    with pytest.raises(CodexClosedError, match="Codex ended"):
        await opening
    assert sink.calls == []


async def test_a_guarded_runs_git_push_is_declined_and_other_commands_asked(
    tmp_path: Path,
) -> None:
    server, run, _, handler = await opened(tmp_path, guard_git=True)

    push = await server.request(
        "item/commandExecution/requestApproval", {"command": "git push", "itemId": "c1"}
    )
    test = await server.request(
        "item/commandExecution/requestApproval", {"command": "npm test", "itemId": "c2"}
    )

    assert push["result"] == {"decision": "decline"}
    assert test["result"] == {"decision": "accept"}
    assert [r.tool_input["command"] for r in handler.requests] == ["npm test"]
    await run.close()


async def test_a_file_change_approval_names_the_items_files(tmp_path: Path) -> None:
    server, run, _, handler = await opened(tmp_path)
    change = {"type": "fileChange", "id": "f1", "changes": [{"path": "/r/a.py", "diff": ""}]}
    server.notify("item/started", item("started", change)["params"])  # type: ignore[arg-type]
    await until(lambda: "f1" in run.stream.file_changes)

    answer = await server.request("item/fileChange/requestApproval", {"itemId": "f1"})

    assert answer["result"] == {"decision": "accept"}
    assert handler.requests[0].tool_input == {"file_path": "/r/a.py"}
    await run.close()
