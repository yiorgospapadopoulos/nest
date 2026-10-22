"""Codex provider on `codex app-server` (B91, D113): plain chats, stage 1.

Each run is one app-server process with one thread: started, or resumed by the thread id
Nest keeps as the session's provider session id. Each user message is a turn
(`turn/start`) with the run's current model, thinking level and permissions, so a changed
model or mode applies from the next turn. A message written into a running turn goes in
with `turn/steer`.

What only Claude does fails cleanly or is reported unsupported (`CODEX_UNSUPPORTED`), so
clients hide it: rewinding files or the conversation, forking, slash commands, stopping
one background task, taking back a steered message, plan review, questions, the task list,
`#` memory and a pixie's skill list. Stage 2 serves a run's Nest tools (a pixie's memory,
habits and Nest actions, artifacts, calling pixies) to Codex as a local MCP server
(`codex_tools`) that the thread's `config` names, so pixies run on Codex and Codex chats
call pixies. The thread's developer instructions name those tools, so the model finds
them among the user's own.
"""

import os
import re
from collections.abc import Mapping
from pathlib import Path

from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.errors import ConflictError
from nestd.local.run import codex_config
from nestd.providers.base import (
    AgentTool,
    ApprovalHandler,
    ContextUsage,
    ForkPoint,
    McpServer,
    ProviderEventSink,
    ProviderFeature,
    RewindResult,
    SessionSpec,
    UserInput,
)
from nestd.providers.claude import agent_env
from nestd.providers.claude_tools import NEST_SERVER, TOOL_SERVER
from nestd.providers.codex_approvals import CodexApprovals, RunPermissions
from nestd.providers.codex_engine import DEFAULT_MODEL, NOT_SIGNED_IN, initialize, read_login
from nestd.providers.codex_events import CodexStream
from nestd.providers.codex_items import items, obj, text
from nestd.providers.codex_modes import CodexPermissions, codex_permissions
from nestd.providers.codex_process import (
    CodexBinary,
    TransportFactory,
    app_server_launch,
    bundled_binary,
    spawn,
)
from nestd.providers.codex_rpc import CodexRpc, JsonObject
from nestd.providers.codex_tools import ToolHost
from nestd.providers.shell_env import ShellEnvSource, no_shell_env

CODEX_UNSUPPORTED: frozenset[ProviderFeature] = frozenset(
    {
        "rewind",
        "fork",
        "slash_commands",
        "stop_task",
        "withdraw",
        "plan_review",
        "questions",
        "task_list",
        "memory",
        "pixie_skills",
    }
)
NO_REWIND = "Codex chats cannot restore files to before a message."
# Codex's approval mode that asks before each call of an MCP tool.
ASK = "prompt"
# What Codex accepts as an MCP server's name; a tool name is kept to the same, so a dotted
# config key cannot be broken by one.
_CONFIG_NAME = re.compile(r"[A-Za-z0-9_-]+")
_CONNECTOR_STATUSES = {
    "connected": "connected",
    "starting": "pending",
    "notStarted": "pending",
    "authenticationRequired": "needs-auth",
    "failed": "failed",
    "cancelled": "failed",
    "disabled": "disabled",
}


class CodexNotSignedInError(ConflictError):
    """Codex has no login, so it cannot run turns (B91)."""

    code = "codex_not_signed_in"

    def __init__(self) -> None:
        super().__init__(NOT_SIGNED_IN)

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class CodexRun:
    steers = True

    def __init__(
        self, spec: SessionSpec, sink: ProviderEventSink, tools: ToolHost | None = None
    ) -> None:
        """`tools` serves the run's Nest tools while it is open; closing the run stops it."""
        self._spec = spec
        self._sink = sink
        self._model = spec.model if spec.local is None else spec.local.model
        self._mode: PermissionMode | None = spec.permission_mode
        self.stream = CodexStream(sink)
        self._rpc: CodexRpc | None = None
        self._tools = tools

    def attach(self, rpc: CodexRpc, thread_id: str) -> None:
        self._rpc = rpc
        self.stream.thread_id = thread_id

    def permissions(self) -> RunPermissions:
        return RunPermissions(
            self._mode, self._spec.guard_git, self._spec.write_root, _nest_servers(self._spec)
        )

    async def closed(self, reason: str) -> None:
        """Codex ended on its own, and with it the run's tools; while the run opens,
        opening fails instead.
        """
        if self._rpc is not None:
            if self._tools is not None:
                await self._tools.close()
            await self._sink.stopped(reason)

    @property
    def rpc(self) -> CodexRpc:
        assert self._rpc is not None  # noqa: S101 (attached once the thread is open)
        return self._rpc

    @property
    def thread_id(self) -> str:
        assert self.stream.thread_id is not None  # noqa: S101 (set with the connection)
        return self.stream.thread_id

    async def send(self, user_input: UserInput) -> None:
        spec = self._spec
        permissions = _permissions(spec, self._mode)
        # A run with a write root writes only there; its other folders are only read.
        writable = () if spec.write_root is not None else spec.extra_dirs
        params: JsonObject = {
            "threadId": self.thread_id,
            "input": _input(user_input),
            "approvalPolicy": permissions.approval_policy,
            "approvalsReviewer": permissions.reviewer,
            "sandboxPolicy": permissions.sandbox_policy(writable),
        }
        if self._model and self._model != DEFAULT_MODEL:
            params["model"] = self._model
        if self._spec.effort is not None:
            params["effort"] = self._spec.effort
        response = await self.rpc.request("turn/start", params)
        turn_id = text(obj(response.get("turn")).get("id"))
        # The answer may come after `turn/started`, which already set it.
        if turn_id and self.stream.turn_id is None:
            self.stream.turn_id = turn_id

    async def steer(self, user_input: UserInput, message_id: str) -> None:
        """Codex reads the message at its next step; a turn goes on while it has unread
        input, so only a Stop loses it. Its echo carries `message_id` (B59).
        """
        turn_id = self.stream.turn_id
        if turn_id is None:
            msg = "no turn is running to write the message into"
            raise RuntimeError(msg)
        self.stream.steered.add(message_id)
        try:
            await self.rpc.request(
                "turn/steer",
                {
                    "threadId": self.thread_id,
                    "expectedTurnId": turn_id,
                    "input": _input(user_input),
                    "clientUserMessageId": message_id,
                },
            )
        except BaseException:
            self.stream.steered.discard(message_id)
            raise

    async def withdraw(self, message_id: str) -> bool:
        """Codex cannot take a message back while its turn runs; once the turn is over it
        no longer has one it did not read, which then waits in Nest's queue again.
        """
        return self.stream.turn_id is None or message_id not in self.stream.steered

    async def interrupt(self) -> None:
        turn_id = self.stream.turn_id
        if turn_id is not None:
            await self.rpc.request(
                "turn/interrupt", {"threadId": self.thread_id, "turnId": turn_id}
            )

    async def set_model(self, model: str | None) -> None:
        self._model = model

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        self._mode = mode

    async def connector_statuses(self) -> list[McpServer]:
        page = await self.rpc.request(
            "mcpServerStatus/list", {"threadId": self.thread_id, "detail": "toolsAndAuthOnly"}
        )
        servers: list[McpServer] = []
        for entry in items(page.get("data")):
            server = obj(entry)
            name = text(server.get("name"))
            if name:
                status = _CONNECTOR_STATUSES.get(text(server.get("runtimeStatus")), "pending")
                servers.append(McpServer(name, status, text(server.get("toolsError")) or None))
        return servers

    async def context_usage(self) -> ContextUsage | None:
        return self.stream.context_usage()

    async def rewind_files(self, checkpoint_id: str, dry_run: bool) -> RewindResult:
        return RewindResult(can_rewind=False, error=NO_REWIND)

    async def stop_task(self, task_id: str) -> bool:
        return False

    async def close(self) -> None:
        try:
            await self.rpc.close()
        finally:
            if self._tools is not None:
                await self._tools.close()


class CodexProvider:
    name = "codex"
    unsupported = CODEX_UNSUPPORTED

    def __init__(
        self,
        gh_config_dir: Path,
        codex_home: Path | None = None,
        transport: TransportFactory = spawn,
        shell_env: ShellEnvSource = no_shell_env,
        binary: CodexBinary | None = None,
        base_env: Mapping[str, str] | None = None,
    ) -> None:
        """`codex_home` is Codex's home (None: Codex's default, `~/.codex`); `base_env` the
        environment runs start from (None: the daemon's).
        """
        self._gh_config_dir = gh_config_dir
        self._codex_home = codex_home
        self._transport = transport
        self._shell_env = shell_env
        self._binary = binary
        self._base_env = base_env

    async def open(
        self, spec: SessionSpec, handler: ApprovalHandler, sink: ProviderEventSink
    ) -> CodexRun:
        servers = {name: tools for name, tools in _served(spec).items() if tools}
        tools = await ToolHost.start(servers) if servers else None
        try:
            run = CodexRun(spec, sink, tools)
            approvals = CodexApprovals(
                handler, run.permissions, run.stream.file_changes.get, run.stream.mcp_call
            )
            extra_env = {
                **(agent_env(self._gh_config_dir) if spec.guard_git else {}),
                **(tools.env() if tools is not None else {}),
                # The account's profile folder (B98) wins over the first account's home.
                **(spec.account.env if spec.account is not None else {}),
            }
            launch = app_server_launch(
                self._binary or bundled_binary(),
                {
                    **(os.environ if self._base_env is None else self._base_env),
                    **await self._shell_env(),
                },
                self._codex_home,
                extra_env,
                spec.cwd,
            )
            transport = await self._transport(launch)
        except BaseException:
            if tools is not None:
                await tools.close()
            raise
        rpc = CodexRpc(transport, run.stream.handle, approvals.handle, run.closed)
        try:
            await initialize(rpc)
            # A local model's own provider needs no login (B106).
            if spec.local is None and not (await read_login(rpc)).signed_in:
                raise CodexNotSignedInError
            config = _thread_config(spec, self._gh_config_dir)
            if spec.local is not None:
                config |= codex_config(spec.local)
            if tools is not None:
                config |= tools.config()
            if spec.guard_git:
                config |= await _ask_before_mcp_tools(rpc, spec)
            thread_id = await self._open_thread(rpc, spec, config)
        except BaseException:
            await rpc.close()
            if tools is not None:
                await tools.close()
            raise
        run.attach(rpc, thread_id)
        await sink.provider_session_id(thread_id)
        return run

    async def fork_point(self, cwd: Path, session_id: str, message_id: str) -> ForkPoint | None:
        """Codex chats are not forked or rewound (CODEX_UNSUPPORTED)."""
        return None

    async def _open_thread(self, rpc: CodexRpc, spec: SessionSpec, config: JsonObject) -> str:
        permissions = _permissions(spec, spec.permission_mode)
        params: JsonObject = {
            "cwd": str(spec.cwd),
            "approvalPolicy": permissions.approval_policy,
            "approvalsReviewer": permissions.reviewer,
            "sandbox": permissions.sandbox,
            "config": config,
        }
        model = spec.model if spec.local is None else spec.local.model
        if model and model != DEFAULT_MODEL:
            params["model"] = model
        instructions = "\n\n".join(
            part for part in (spec.system_prompt_append, _tools_hint(spec)) if part
        )
        if instructions:
            params["developerInstructions"] = instructions
        if spec.resume_id is not None:
            response = await rpc.request("thread/resume", {"threadId": spec.resume_id, **params})
        else:
            response = await rpc.request("thread/start", params)
        thread_id = text(obj(response.get("thread")).get("id"))
        if not thread_id:
            msg = "Codex opened no thread"
            raise RuntimeError(msg)
        return thread_id


def _permissions(spec: SessionSpec, mode: PermissionMode | None) -> CodexPermissions:
    return codex_permissions(mode, spec.guard_git, spec.write_root, spec.cwd)


def _served(spec: SessionSpec) -> dict[str, tuple[AgentTool, ...]]:
    """Nest's MCP servers for the run, named as Claude's runs have them (`claude_tools`)."""
    return {TOOL_SERVER: spec.tools, NEST_SERVER: spec.nest_tools}


def _tools_hint(spec: SessionSpec) -> str:
    """A line naming the run's Nest tools, which the model may not find among the user's
    many MCP tools on its own; empty without any.
    """
    groups = [
        ", ".join(f"mcp__{server}__{tool.name}" for tool in tools) + f" (the {server} server)"
        for server, tools in _served(spec).items()
        if tools
    ]
    if not groups:
        return ""
    return f"Nest's tools for this chat are MCP tools: {' and '.join(groups)}."


def _nest_servers(spec: SessionSpec) -> frozenset[str]:
    return frozenset(name for name, tools in _served(spec).items() if tools)


async def _ask_before_mcp_tools(rpc: CodexRpc, spec: SessionSpec) -> JsonObject:
    """A guarded run's overrides that make Codex ask before every tool of the user's own MCP
    servers, so each call comes to Nest, which declines git writes (`CodexApprovals`): every
    server's default and each tool the user set to run without asking. Nest's own servers,
    which replace same-named ones, and names Codex would refuse are left out.
    """
    response = await rpc.request("config/read", {"cwd": str(spec.cwd)})
    servers = obj(obj(response.get("config")).get("mcp_servers"))
    own = _nest_servers(spec)
    config: JsonObject = {}
    for name, entry in servers.items():
        if name in own or not _CONFIG_NAME.fullmatch(name):
            continue
        config[f"mcp_servers.{name}.default_tools_approval_mode"] = ASK
        for tool in obj(obj(entry).get("tools")):
            if _CONFIG_NAME.fullmatch(tool):
                config[f"mcp_servers.{name}.tools.{tool}.approval_mode"] = ASK
    return config


def _thread_config(spec: SessionSpec, gh_config_dir: Path) -> JsonObject:
    """Config overrides for the thread, as `-c key=value` would give them. A guarded run's
    commands also get the credential-free git setup (D013), whatever the user's shell
    environment policy leaves out.
    """
    config: JsonObject = {}
    if spec.guard_git:
        env: dict[str, JsonValue] = dict(agent_env(gh_config_dir))
        config["shell_environment_policy.set"] = env
    return config


def _input(user_input: UserInput) -> list[JsonValue]:
    message = user_input.text
    if user_input.file_paths:
        listing = "\n".join(f"- {path}" for path in user_input.file_paths)
        message = f"{message}\n\nAttached files:\n{listing}"
    parts: list[JsonValue] = [
        {"type": "image", "url": f"data:{image.media_type};base64,{image.data}"}
        for image in user_input.images
    ]
    parts.append({"type": "text", "text": message, "text_elements": []})
    return parts
