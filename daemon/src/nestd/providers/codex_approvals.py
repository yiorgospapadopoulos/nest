"""Codex's requests to its client: command, file change and MCP tool call approvals go to
the user through Nest's approval handler; the rest Nest declines (B91, D113).

A guarded run's git writes are declined before anyone is asked (D013), with the matchers the
Claude side uses: `is_git_write` for commands (the whole command, shell wrapper included),
`tool_writes` for MCP tool calls (a tool named like `create_pull_request`, or one whose
input holds a git write command). Codex asks before an MCP tool call as an MCP elicitation
marked `codex_approval_kind: mcp_tool_call` with the tool's input in its `_meta` but not its
name: that comes from the `mcpToolCall` item Codex started just before in the turn, else
from the elicitation's message, and a guarded run declines a call it cannot name. Nest's
own tools are accepted, since they check their callers themselves. "Always allow" accepts
for the rest of Codex's session: a command by its exact text (the user sees the command
inside Codex's shell wrapper), file changes as a whole. Nest never accepts an execpolicy
amendment, which would change the user's Codex rules for good.

A run with a write root (a pixie's, D072) has every file change outside it declined, in
every mode, as Claude's write guard denies it.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.providers.base import ApprovalHandler, PermissionRequest
from nestd.providers.codex_items import file_paths, obj, shown_command, text
from nestd.providers.codex_modes import command_decision, file_change_decision
from nestd.providers.codex_rpc import METHOD_NOT_FOUND, CodexRpcError, JsonObject
from nestd.providers.git_guard import tool_writes

COMMAND_APPROVAL = "item/commandExecution/requestApproval"
FILE_APPROVAL = "item/fileChange/requestApproval"
PERMISSIONS_APPROVAL = "item/permissions/requestApproval"
ELICITATION = "mcpServer/elicitation/request"
TOOL_CALL_APPROVAL = "mcp_tool_call"
_ACCEPT: JsonValue = {"action": "accept", "content": {}, "_meta": None}
_DECLINE: JsonValue = {"action": "decline", "content": None, "_meta": None}
_MESSAGE_TOOL = re.compile(r'run tool "([^"]+)"')


@dataclass(frozen=True)
class RunPermissions:
    """What a run's approvals depend on, read when each one comes."""

    mode: PermissionMode | None
    guarded: bool
    # File changes outside it are declined in every mode (D072).
    write_root: Path | None = None
    # The MCP servers that are Nest's own tools for this run.
    nest_servers: frozenset[str] = frozenset()


class CodexApprovals:
    def __init__(
        self,
        handler: ApprovalHandler,
        permissions: Callable[[], RunPermissions],
        file_changes: Callable[[str], JsonObject | None],
        mcp_calls: Callable[[str, str], JsonObject | None],
    ) -> None:
        """`file_changes` finds the file change item an approval is for, by item id;
        `mcp_calls` the MCP tool call in progress, by server and turn.
        """
        self._handler = handler
        self._permissions = permissions
        self._file_changes = file_changes
        self._mcp_calls = mcp_calls

    async def handle(self, method: str, params: JsonObject) -> JsonValue:
        if method == COMMAND_APPROVAL:
            return {"decision": await self._command(params)}
        if method == FILE_APPROVAL:
            return {"decision": await self._file_change(params)}
        if method == PERMISSIONS_APPROVAL:
            # Extra sandbox permissions are never granted: the mode decides the sandbox.
            return {"permissions": {}, "scope": "turn"}
        if method == ELICITATION:
            return await self._elicitation(params)
        msg = f"Nest does not answer {method}"
        raise CodexRpcError(METHOD_NOT_FOUND, msg)

    async def _command(self, params: JsonObject) -> str:
        command = text(params.get("command"))
        permissions = self._permissions()
        auto = command_decision(command, permissions.mode, permissions.guarded)
        if auto is not None:
            return auto
        # The user sees the command inside Codex's shell wrapper; Codex keeps a session's
        # acceptance for the exact command it asked about.
        shown = shown_command(command)
        tool_input: dict[str, JsonValue] = {"command": shown}
        cwd = text(params.get("cwd"))
        if cwd:
            tool_input["cwd"] = cwd
        decision = await self._handler.decide(
            PermissionRequest(
                tool_name="Bash",
                tool_input=tool_input,
                reason=text(params.get("reason")) or None,
                always_rule=f"Bash({shown})",
            )
        )
        return _answer(decision.behavior == "allow", decision.always)

    async def _file_change(self, params: JsonObject) -> str:
        permissions = self._permissions()
        item = self._file_changes(text(params.get("itemId"))) or {}
        paths = file_paths(item)
        root = permissions.write_root
        if root is not None and not (paths and all(_within(path, root) for path in paths)):
            return "decline"
        auto = file_change_decision(permissions.mode)
        if auto is not None:
            return auto
        tool_input: dict[str, JsonValue] = {"file_path": paths[0] if paths else ""}
        if len(paths) > 1:
            tool_input["file_paths"] = list[JsonValue](paths)
        decision = await self._handler.decide(
            PermissionRequest(
                tool_name="Edit",
                tool_input=tool_input,
                reason=text(params.get("reason")) or None,
            )
        )
        return _answer(decision.behavior == "allow", decision.always)

    async def _elicitation(self, params: JsonObject) -> JsonValue:
        """An MCP tool call approval is decided like a tool permission; any other question
        an MCP server asks is declined.
        """
        meta = obj(params.get("_meta"))
        if meta.get("codex_approval_kind") != TOOL_CALL_APPROVAL:
            return _DECLINE
        permissions = self._permissions()
        server = text(params.get("serverName"))
        if server in permissions.nest_servers:
            return _ACCEPT
        # Codex names the tool only in its message; the call it started just before has it.
        call = self._mcp_calls(server, text(params.get("turnId"))) or {}
        message = text(params.get("message"))
        tool = text(call.get("tool")) or _message_tool(message)
        tool_input = obj(meta.get("tool_params")) or obj(call.get("arguments"))
        name = f"mcp__{server}__{tool}"
        if permissions.guarded and (not tool or tool_writes(name, tool_input)):
            return _DECLINE
        if permissions.mode == "bypassPermissions":
            return _ACCEPT
        decision = await self._handler.decide(
            PermissionRequest(
                tool_name=name,
                tool_input=dict(tool_input),
                reason=message or None,
            )
        )
        return _ACCEPT if decision.behavior == "allow" else _DECLINE


def _message_tool(message: str) -> str:
    """The tool an approval message names: 'Allow the X MCP server to run tool "js"?'."""
    found = _MESSAGE_TOOL.search(message)
    return found.group(1) if found else ""


def _within(path: str, root: Path) -> bool:
    """Whether an absolute `path` is `root` or inside it; a relative one cannot be judged."""
    candidate = Path(path)
    if not candidate.is_absolute():
        return False
    resolved = candidate.resolve()
    target = root.resolve()
    return resolved == target or target in resolved.parents


def _answer(allowed: bool, always: bool) -> str:
    if not allowed:
        return "decline"
    return "acceptForSession" if always else "accept"
