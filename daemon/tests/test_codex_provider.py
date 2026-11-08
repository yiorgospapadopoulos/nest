import asyncio
import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from nestd.config.models import PermissionMode
from nestd.providers.base import (
    ForkPoint,
    ImageInput,
    McpServer,
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
    UserInput,
)
from nestd.providers.codex import (
    CODEX_UNSUPPORTED,
    NO_REWIND,
    QUESTIONS_CONFIG,
    CodexNotSignedInError,
    CodexProvider,
    CodexRun,
)
from nestd.providers.codex_engine import NOT_SIGNED_IN
from nestd.providers.codex_process import CODEX_HOME_ENV, CodexBinary
from nestd.providers.codex_rpc import CodexClosedError, CodexRpcError, JsonObject
from nestd.providers.push_block import NO_PUSH_ENV, helpers, subagent_hook_args
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
    # A normal chat's subagents may not push (B127): Codex's own hook stops them.
    assert launch.args == (
        str(tmp_path / "codex"),
        "app-server",
        "--listen",
        "stdio://",
        *subagent_hook_args(helpers()),
    )
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
            "config": QUESTIONS_CONFIG,
            "developerInstructions": "You are running inside Nest.",
        }
    ]
    assert sink.calls == [("provider_session_id", "thread-1")]
    assert run.steers
    await run.close()
    assert server.transport.closed


async def test_a_run_on_an_added_account_starts_codex_on_its_profile(tmp_path: Path) -> None:
    """B98: its own home for the login, the first account's for the SQLite state."""
    account = RunAccount(
        "0123456789ab",
        {"CODEX_HOME": str(tmp_path / "profile"), "CODEX_SQLITE_HOME": str(tmp_path / "first")},
    )

    server, run, _, _ = await opened(tmp_path, account=account)

    env = server.launches[0].env
    assert env[CODEX_HOME_ENV] == str(tmp_path / "profile")
    assert env["CODEX_SQLITE_HOME"] == str(tmp_path / "first")
    await run.close()


async def test_a_guarded_run_has_the_git_level_block_in_codex_and_its_commands(
    tmp_path: Path,
) -> None:
    server, run, _, _ = await opened(tmp_path, guard_git=True, model="gpt-5.5")

    env = server.launches[0].env
    assert env["GIT_CONFIG_KEY_0"] == NO_PUSH_ENV["GIT_CONFIG_KEY_0"]
    assert "GH_CONFIG_DIR" not in env
    [start] = server.requests("thread/start")
    assert start["model"] == "gpt-5.5"
    # Nest's gh comes first for the commands and for Codex itself (D160).
    assert start["config"] == {
        "shell_environment_policy.set": {**NO_PUSH_ENV, "PATH": env["PATH"]},
        **QUESTIONS_CONFIG,
    }
    assert env["PATH"].startswith(f"{helpers()}{os.pathsep}")
    assert "developerInstructions" not in start
    await run.close()


async def test_a_run_without_history_starts_an_ephemeral_thread(tmp_path: Path) -> None:
    """B115: the performance check's tiny turns stay out of Codex's own thread list."""
    server, run, _, _ = await opened(tmp_path)
    once_server, once, _, _ = await opened(tmp_path, keep_history=False)

    [start] = server.requests("thread/start")
    [once_start] = once_server.requests("thread/start")
    assert "ephemeral" not in start
    assert once_start["ephemeral"] is True
    await run.close()
    await once.close()


@pytest.mark.parametrize(
    "fields", [{"guard_git": True}, {"guard_git": False, "guard_subagents": False}]
)
async def test_codexs_subagent_hook_is_only_for_a_chat_that_may_push_alone(
    tmp_path: Path, fields: dict[str, bool]
) -> None:
    """A guarded run asks Nest about every command; with agents allowed to push, nothing
    is blocked."""
    server, run, _, _ = await opened(tmp_path, **fields)

    assert "-c" not in server.launches[0].args
    await run.close()


async def test_a_runs_folder_ports_reach_codex_and_its_commands(tmp_path: Path) -> None:
    """B108: set for the commands too, whatever the user's environment policy passes on."""
    ports = {"NEST_PORT": "41020", "NEST_PORT_1": "41021"}

    server, run, _, _ = await opened(tmp_path, env=ports)
    guarded_server, guarded, _, _ = await opened(tmp_path, env=ports, guard_git=True)

    assert server.launches[0].env["NEST_PORT"] == "41020"
    [start] = server.requests("thread/start")
    assert start["config"] == {"shell_environment_policy.set": ports, **QUESTIONS_CONFIG}
    [guarded_start] = guarded_server.requests("thread/start")
    guarded_path = guarded_server.launches[0].env["PATH"]
    assert guarded_path.startswith(f"{helpers()}{os.pathsep}")
    assert guarded_start["config"] == {
        "shell_environment_policy.set": {**ports, **NO_PUSH_ENV, "PATH": guarded_path},
        **QUESTIONS_CONFIG,
    }
    await run.close()
    await guarded.close()


async def test_a_chosen_size_to_compact_at_reaches_codexs_own_setting(tmp_path: Path) -> None:
    """B146: Codex compacts by itself at the chat's size; without one, at its own."""
    server, run, _, _ = await opened(tmp_path, compact_at=300_000)
    auto_server, auto, _, _ = await opened(tmp_path)

    [start] = server.requests("thread/start")
    [auto_start] = auto_server.requests("thread/start")
    config, auto_config = start["config"], auto_start["config"]
    assert isinstance(config, dict)
    assert isinstance(auto_config, dict)
    assert config["model_auto_compact_token_limit"] == 300_000
    assert "model_auto_compact_token_limit" not in auto_config
    await run.close()
    await auto.close()


async def test_a_session_with_a_thread_resumes_it(tmp_path: Path) -> None:
    server, run, sink, _ = await opened(tmp_path, resume_id="thread-7")

    [resume] = server.requests("thread/resume")
    assert resume["threadId"] == "thread-7"
    assert resume["cwd"] == str(tmp_path)
    assert sink.calls == [("provider_session_id", "thread-7")]
    await run.close()


async def test_a_cut_conversation_is_codexs_fork_through_the_kept_turn(tmp_path: Path) -> None:
    """B145: a rewind or fork opens a new thread holding the turns up to the cut, and the
    next message's checkpoint is the last of them.
    """
    server = FakeAppServer()
    server.answers["thread/fork"] = {
        "thread": {"id": "thread-8", "turns": [{"id": "turn-1"}, {"id": "turn-2"}]}
    }
    sink = RecordingSink()
    codex = provider(tmp_path, server)
    run = await codex.open(
        spec(tmp_path, resume_id="thread-7", resume_at="turn-2"), Handler(), sink
    )

    [fork] = server.requests("thread/fork")
    assert (fork["threadId"], fork["lastTurnId"], fork["cwd"]) == (
        "thread-7",
        "turn-2",
        str(tmp_path),
    )
    assert server.requests("thread/resume") == []
    assert sink.calls == [("provider_session_id", "thread-8")]
    assert run.stream.last_turn == "turn-2"
    assert await codex.fork_point(tmp_path, "thread-8", "turn-2") == ForkPoint("turn-2")
    # Before the thread's first message nothing is kept; inside a turn there is no cut.
    assert await codex.fork_point(tmp_path, "thread-8", "") == ForkPoint(None)
    assert await codex.fork_point(tmp_path, "thread-8", "steered:u3") is None
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
    codex = CodexProvider(transport=server)

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
    await until(lambda: ("message_taken", ("q1", "steered:u2")) in sink.calls)

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


async def test_what_codex_lacks_fails_cleanly(tmp_path: Path) -> None:
    server, run, _, _ = await opened(tmp_path)
    codex = provider(tmp_path, server)

    rewind = await run.rewind_files("cp-1", dry_run=True)

    assert (rewind.can_rewind, rewind.error) == (False, NO_REWIND)
    assert not await run.stop_task("task-1")
    assert await run.context_usage() is None
    assert {"slash_commands", "withdraw"} == CODEX_UNSUPPORTED
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
    commit = await server.request(
        "item/commandExecution/requestApproval", {"command": "git commit -m wip", "itemId": "c3"}
    )

    assert push["result"] == {"decision": "decline"}
    assert test["result"] == commit["result"] == {"decision": "accept"}
    # A pixie may commit (D123); with no sandbox beyond Claude's, it is asked like any other.
    assert [r.tool_input["command"] for r in handler.requests] == ["npm test", "git commit -m wip"]
    [start] = server.requests("thread/start")
    assert (start["approvalPolicy"], start["sandbox"]) == ("untrusted", "danger-full-access")
    [init] = server.requests("initialize")
    assert init["capabilities"] == {"experimentalApi": True, "requestAttestation": False}
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


class PlanHandler(Handler):
    def __init__(self, *decisions: PlanDecision) -> None:
        super().__init__()
        self.decisions = list(decisions)
        self.plans: list[str] = []

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        self.plans.append(request.plan)
        return self.decisions.pop(0)


def planned(text: str) -> list[JsonObject]:
    return [item("completed", {"type": "plan", "id": "p1", "text": text}), turn_completed()]


def results(sink: RecordingSink) -> list[object]:
    return [value for kind, value in sink.calls if kind == "result"]


async def test_an_approved_codex_plan_goes_on_in_the_chosen_mode(tmp_path: Path) -> None:
    """B145: Codex's own plan mode, and its "Implement this plan?" as Nest's plan review."""
    server = FakeAppServer()
    server.script(*planned("1. Do it"))
    server.script(turn_completed())
    sink = RecordingSink()
    handler = PlanHandler(PlanDecision(approved=True, mode="acceptEdits"))
    run = await provider(tmp_path, server).open(
        spec(tmp_path, permission_mode="plan"), handler, sink
    )

    await run.send(UserInput("Plan it"))
    await until(lambda: len(results(sink)) == 1)

    assert handler.plans == ["1. Do it"]
    first, second = server.requests("turn/start")
    assert first["collaborationMode"] == {
        "mode": "plan",
        "settings": {"model": "gpt-6.1-sol", "developer_instructions": None},
    }
    assert second["input"] == [{"type": "text", "text": "Implement the plan.", "text_elements": []}]
    assert second["collaborationMode"]["mode"] == "default"  # type: ignore[index]
    assert ("permission_mode", "acceptEdits") in sink.calls
    await run.close()


async def test_a_plan_kept_without_words_ends_the_turn(tmp_path: Path) -> None:
    server = FakeAppServer()
    server.script(*planned("1. Do it"))
    sink = RecordingSink()
    handler = PlanHandler(PlanDecision(approved=False))
    run = await provider(tmp_path, server).open(
        spec(tmp_path, permission_mode="plan"), handler, sink
    )

    await run.send(UserInput("Plan it"))
    await until(lambda: len(results(sink)) == 1)

    assert len(server.requests("turn/start")) == 1
    await run.close()
