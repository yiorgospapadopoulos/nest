from pathlib import Path

import pytest

from nestd.config.models import PermissionMode
from nestd.providers.base import (
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    QuestionAnswer,
    QuestionRequest,
)
from nestd.providers.codex_approvals import CodexApprovals, RunPermissions
from nestd.providers.codex_rpc import METHOD_NOT_FOUND, CodexRpcError, JsonObject


class Handler:
    def __init__(self, decision: PermissionDecision | None = None) -> None:
        self.decision = decision or PermissionDecision("allow")
        self.requests: list[PermissionRequest] = []

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        self.requests.append(request)
        return self.decision

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        raise AssertionError

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        raise AssertionError


def approvals(
    handler: Handler,
    mode: PermissionMode | None = "default",
    guarded: bool = False,
    changes: dict[str, JsonObject] | None = None,
    write_root: Path | None = None,
    calls: dict[tuple[str, str], JsonObject] | None = None,
) -> CodexApprovals:
    """`calls` are the MCP tool calls in progress, by server and turn."""
    permissions = RunPermissions(mode, guarded, write_root, frozenset({"nest", "pixie"}))
    pending = calls or {}
    return CodexApprovals(
        handler,
        lambda: permissions,
        (changes or {}).get,
        lambda server, turn: pending.get((server, turn)),
    )


def command(text: str) -> JsonObject:
    return {"threadId": "t", "itemId": "c1", "command": text, "cwd": "/r", "reason": "needs net"}


async def test_a_command_goes_to_the_user_as_a_bash_prompt_with_its_rule() -> None:
    handler = Handler()

    answer = await approvals(handler).handle(
        "item/commandExecution/requestApproval", command("npm install")
    )

    assert answer == {"decision": "accept"}
    assert handler.requests == [
        PermissionRequest(
            tool_name="Bash",
            tool_input={"command": "npm install", "cwd": "/r"},
            reason="needs net",
            always_rule="Bash(npm install)",
        )
    ]


@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (PermissionDecision("allow", always=True), "acceptForSession"),
        (PermissionDecision("deny", "no"), "decline"),
    ],
)
async def test_the_users_answer_becomes_codexs_decision(
    decision: PermissionDecision, expected: str
) -> None:
    answer = await approvals(Handler(decision)).handle(
        "item/commandExecution/requestApproval", {"command": "make"}
    )

    assert answer == {"decision": expected}


async def test_a_wrapped_command_is_asked_and_always_allowed_by_its_inner_command() -> None:
    handler = Handler(PermissionDecision("allow", always=True))

    answer = await approvals(handler).handle(
        "item/commandExecution/requestApproval",
        command("/bin/zsh -lc \"sed -n '1,20p' notes.txt\""),
    )

    # Codex keeps the session's acceptance for the exact command it asked about.
    assert answer == {"decision": "acceptForSession"}
    assert handler.requests[0].tool_input == {"command": "sed -n '1,20p' notes.txt", "cwd": "/r"}
    assert handler.requests[0].always_rule == "Bash(sed -n '1,20p' notes.txt)"


async def test_a_guarded_runs_wrapped_git_write_is_declined_without_asking() -> None:
    handler = Handler()

    answer = await approvals(handler, guarded=True).handle(
        "item/commandExecution/requestApproval", command("/bin/zsh -lc 'git push origin x'")
    )

    assert answer == {"decision": "decline"}
    assert handler.requests == []


async def test_a_guarded_runs_git_write_is_declined_without_asking() -> None:
    handler = Handler()

    answer = await approvals(handler, guarded=True).handle(
        "item/commandExecution/requestApproval", command("git push origin main")
    )

    assert answer == {"decision": "decline"}
    assert handler.requests == []


async def test_a_command_without_cwd_or_reason_is_asked_as_is() -> None:
    handler = Handler()

    await approvals(handler).handle("item/commandExecution/requestApproval", {})

    assert handler.requests[0].tool_input == {"command": ""}
    assert handler.requests[0].reason is None


async def test_a_file_change_goes_to_the_user_as_an_edit_of_its_files() -> None:
    handler = Handler(PermissionDecision("allow", always=True))
    change: JsonObject = {
        "type": "fileChange",
        "id": "f1",
        "changes": [{"path": "/r/a.py"}, {"path": "/r/b.py"}],
    }

    answer = await approvals(handler, changes={"f1": change}).handle(
        "item/fileChange/requestApproval", {"itemId": "f1", "reason": None}
    )

    assert answer == {"decision": "acceptForSession"}
    assert handler.requests == [
        PermissionRequest(
            tool_name="Edit",
            tool_input={"file_path": "/r/a.py", "file_paths": ["/r/a.py", "/r/b.py"]},
        )
    ]


async def test_an_unknown_file_change_is_still_asked() -> None:
    handler = Handler(PermissionDecision("deny"))

    answer = await approvals(handler).handle("item/fileChange/requestApproval", {"itemId": "x"})

    assert answer == {"decision": "decline"}
    assert handler.requests[0].tool_input == {"file_path": ""}


async def test_file_changes_are_accepted_in_accept_edits_without_asking() -> None:
    handler = Handler()

    answer = await approvals(handler, mode="acceptEdits").handle(
        "item/fileChange/requestApproval", {"itemId": "f1"}
    )

    assert answer == {"decision": "accept"}
    assert handler.requests == []


async def test_extra_permissions_and_elicitations_are_declined() -> None:
    codex = approvals(Handler())

    assert await codex.handle("item/permissions/requestApproval", {}) == {
        "permissions": {},
        "scope": "turn",
    }
    assert await codex.handle("mcpServer/elicitation/request", {}) == {
        "action": "decline",
        "content": None,
        "_meta": None,
    }


async def test_other_requests_are_refused() -> None:
    with pytest.raises(CodexRpcError) as raised:
        await approvals(Handler()).handle("item/tool/call", {})

    assert raised.value.code == METHOD_NOT_FOUND


def tool_approval(
    server: str, tool: str | None, params: JsonObject | None = None, turn: str = "u"
) -> JsonObject:
    """How Codex asks before an MCP tool call, as recorded live (B91): a form elicitation
    whose meta holds the tool's input and description but not its name, which only the
    message gives.
    """
    meta: JsonObject = {
        "codex_approval_kind": "mcp_tool_call",
        "tool_description": "Runs the tool.",
    }
    if params is not None:
        meta["tool_params"] = params
        meta["tool_params_display"] = [
            {"name": key, "value": value, "display_name": key} for key, value in params.items()
        ]
    message = f'Allow the {server} MCP server to run tool "{tool}"?' if tool else "Allow?"
    return {
        "threadId": "t",
        "turnId": turn,
        "serverName": server,
        "mode": "form",
        "_meta": meta,
        "message": message,
        "requestedSchema": {"type": "object", "properties": {}},
    }


def call(server: str, tool: str, arguments: JsonObject | None = None) -> JsonObject:
    """The `mcpToolCall` item Codex starts just before it asks."""
    return {
        "type": "mcpToolCall",
        "id": f"exec-{tool}",
        "server": server,
        "tool": tool,
        "status": "inProgress",
        "arguments": arguments or {},
    }


ACCEPT: JsonObject = {"action": "accept", "content": {}, "_meta": None}
DECLINE: JsonObject = {"action": "decline", "content": None, "_meta": None}


async def test_an_mcp_tool_call_approval_goes_to_the_user_by_its_calls_tool_name() -> None:
    handler = Handler()
    calls = {("github", "u"): call("github", "list_issues", {"repo": "me/nest"})}

    answer = await approvals(handler, calls=calls).handle(
        "mcpServer/elicitation/request",
        tool_approval("github", "list_issues", {"repo": "me/nest"}),
    )

    assert answer == ACCEPT
    assert handler.requests == [
        PermissionRequest(
            tool_name="mcp__github__list_issues",
            tool_input={"repo": "me/nest"},
            reason='Allow the github MCP server to run tool "list_issues"?',
        )
    ]


async def test_the_calls_arguments_are_the_input_when_the_meta_has_none() -> None:
    handler = Handler()
    calls = {("node_repl", "u"): call("node_repl", "js", {"code": "1+1"})}

    await approvals(handler, calls=calls).handle(
        "mcpServer/elicitation/request", tool_approval("node_repl", "js")
    )

    assert handler.requests[0].tool_name == "mcp__node_repl__js"
    assert handler.requests[0].tool_input == {"code": "1+1"}


async def test_without_a_call_the_tool_name_comes_from_the_message() -> None:
    handler = Handler()
    # A call of the same server in another turn is not this one.
    calls = {("node_repl", "earlier"): call("node_repl", "js_reset")}

    await approvals(handler, calls=calls).handle(
        "mcpServer/elicitation/request", tool_approval("node_repl", "js", {"code": "1+1"})
    )

    assert handler.requests[0].tool_name == "mcp__node_repl__js"
    assert handler.requests[0].tool_input == {"code": "1+1"}


async def test_a_denied_mcp_tool_call_is_declined() -> None:
    answer = await approvals(Handler(PermissionDecision("deny"))).handle(
        "mcpServer/elicitation/request", tool_approval("github", "list_issues")
    )

    assert answer == DECLINE


@pytest.mark.parametrize(
    ("server", "tool", "params"),
    [
        ("github", "create_pull_request", {}),
        ("github", "merge_pull_request", {"number": 3}),
        ("git", "git_push", {}),
        ("serena", "execute_shell_command", {"command": "git push origin main"}),
        ("shell", "run", {"args": ["gh", "pr", "create"]}),
    ],
)
@pytest.mark.parametrize("known", [True, False])
async def test_a_guarded_runs_git_writing_mcp_call_is_declined_without_asking(
    server: str, tool: str, params: JsonObject, known: bool
) -> None:
    """Judged by the call's tool name, or the message's when no call is known."""
    handler = Handler()
    calls = {(server, "u"): call(server, tool, params)} if known else {}

    answer = await approvals(handler, mode="bypassPermissions", guarded=True, calls=calls).handle(
        "mcpServer/elicitation/request", tool_approval(server, tool, params)
    )

    assert answer == DECLINE
    assert handler.requests == []


async def test_a_guarded_run_declines_a_call_no_tool_can_be_named_for() -> None:
    handler = Handler()

    answer = await approvals(handler, guarded=True).handle(
        "mcpServer/elicitation/request", tool_approval("github", None, {})
    )

    assert answer == DECLINE
    assert handler.requests == []


async def test_a_guarded_runs_other_mcp_calls_are_asked_or_accepted_in_bypass() -> None:
    handler = Handler()
    calls = {("serena", "u"): call("serena", "execute_shell_command")}
    asked = approvals(handler, guarded=True, calls=calls)
    bypass = approvals(handler, mode="bypassPermissions", guarded=True, calls=calls)
    request = tool_approval("serena", "execute_shell_command", {"command": "git status"})

    assert await asked.handle("mcpServer/elicitation/request", request) == ACCEPT
    assert await bypass.handle("mcpServer/elicitation/request", request) == ACCEPT
    assert [r.tool_name for r in handler.requests] == ["mcp__serena__execute_shell_command"]


async def test_nests_own_tools_are_accepted_without_asking() -> None:
    handler = Handler()

    answer = await approvals(handler, guarded=True).handle(
        "mcpServer/elicitation/request", tool_approval("nest", "create_artifact", {})
    )

    assert answer == ACCEPT
    assert handler.requests == []


async def test_an_mcp_servers_own_question_is_still_declined() -> None:
    handler = Handler()
    question: JsonObject = {
        "serverName": "github",
        "mode": "form",
        "message": "Which org?",
        "requestedSchema": {"type": "object", "properties": {"org": {"type": "string"}}},
        "_meta": None,
    }

    answer = await approvals(handler).handle("mcpServer/elicitation/request", question)

    assert answer == DECLINE
    assert handler.requests == []


async def test_a_file_change_outside_the_write_root_is_declined_in_every_mode(
    tmp_path: Path,
) -> None:
    handler = Handler()
    root = tmp_path / "workdir"
    inside: JsonObject = {"changes": [{"path": str(root / "notes.md")}]}
    outside: JsonObject = {"changes": [{"path": str(root / "a.md")}, {"path": "/r/app.py"}]}
    relative: JsonObject = {"changes": [{"path": "app.py"}]}
    codex = approvals(
        handler,
        mode="bypassPermissions",
        changes={"in": inside, "out": outside, "rel": relative},
        write_root=root,
    )

    assert await codex.handle("item/fileChange/requestApproval", {"itemId": "in"}) == {
        "decision": "accept"
    }
    for item_id in ("out", "rel", "unknown"):
        assert await codex.handle("item/fileChange/requestApproval", {"itemId": item_id}) == {
            "decision": "decline"
        }
    assert handler.requests == []
