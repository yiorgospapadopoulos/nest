"""Claude provider on the Claude Agent SDK (D003), with the agent git block layers (D013)
for the runs that keep them (B58)."""

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import (
    AgentDefinition,
    ClaudeAgentOptions,
    ClaudeSDKClient,
    ContextUsageResponse,
    HookMatcher,
    McpStatusResponse,
    Message,
    PermissionResult,
    PermissionResultAllow,
    PermissionResultDeny,
    PermissionUpdate,
    ToolPermissionContext,
)
from claude_agent_sdk.types import PermissionMode as SdkPermissionMode
from claude_agent_sdk.types import SystemPromptPreset
from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.gitops.remotes import scrub_credentials
from nestd.logging_setup import ENGINE_STDERR_LOGGER
from nestd.providers.base import (
    ApprovalHandler,
    ContextUsage,
    ForkPoint,
    McpServer,
    PermissionRequest,
    PlanRequest,
    ProviderEventSink,
    RewindResult,
    SessionSpec,
    Subagent,
    UserInput,
)
from nestd.providers.claude_commands import context_usage, described_catalog
from nestd.providers.claude_engine import engine_details
from nestd.providers.claude_fork import fork_point
from nestd.providers.claude_messages import (
    BackgroundTasks,
    TurnOutput,
    mcp_servers,
    translate,
)
from nestd.providers.claude_questions import (
    ASK_USER_QUESTION,
    QUESTION_TIMEOUT_SECONDS,
    QuestionBridge,
)
from nestd.providers.claude_rewind import rewind
from nestd.providers.claude_rules import always_updates
from nestd.providers.claude_steering import engine_uuid, withdraw
from nestd.providers.claude_thinking import ThinkingTimer
from nestd.providers.claude_tools import (
    SUBAGENT_DENIED,
    WRITE_TOOLS,
    own_tool_names,
    subagent_guard,
    tool_servers,
    write_guard,
)
from nestd.providers.git_guard import GIT_WRITE_RULES, block_git_writes
from nestd.providers.shell_env import ShellEnvSource, no_shell_env

DEFAULT_DENY_MESSAGE = "The user denied this action."
# What the SDK puts in a crash's message where the CLI's own error belongs.
STDERR_PLACEHOLDER = "Check stderr output for details"
STDERR_LINES = 20
STDERR_CHARS = 300
# The tool Claude calls in plan mode to present its plan and ask to start working (D032).
EXIT_PLAN_MODE = "ExitPlanMode"
KEEP_PLANNING_MESSAGE = "Keep planning."
# The longest stream message the run reads. Each is one line, and a tool result with an
# image is base64 in it; the SDK's 1 MB default would end the run on such a read (PL-14).
MAX_MESSAGE_BYTES = 64 * 1024 * 1024

logger = logging.getLogger(__name__)
stderr_logger = logging.getLogger(ENGINE_STDERR_LOGGER)


class SdkClient(Protocol):
    """The part of ClaudeSDKClient the provider uses; tests substitute a fake."""

    async def connect(self) -> None: ...

    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = ...
    ) -> None: ...

    def receive_messages(self) -> AsyncIterator[Message]: ...

    async def interrupt(self) -> None: ...

    async def set_model(self, model: str | None = ...) -> None: ...

    async def set_permission_mode(self, mode: SdkPermissionMode) -> None: ...

    async def get_mcp_status(self) -> McpStatusResponse: ...

    async def stop_task(self, task_id: str) -> None: ...

    async def get_context_usage(self) -> ContextUsageResponse: ...

    async def get_server_info(self) -> dict[str, Any] | None: ...

    async def disconnect(self) -> None: ...


type ClientFactory = Callable[[ClaudeAgentOptions], SdkClient]


def agent_env(gh_config_dir: Path) -> dict[str, str]:
    """Layer 3 of a guarded run: no git credential helpers, prompts or GitHub token."""
    return {
        # An empty credential.helper resets every configured helper.
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "credential.helper",
        "GIT_CONFIG_VALUE_0": "",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ASKPASS": "/usr/bin/false",
        "GH_CONFIG_DIR": str(gh_config_dir),
        # The SDK merges this over the daemon's environment, so tokens are blanked, not removed.
        "GH_TOKEN": "",
        "GITHUB_TOKEN": "",
    }


# How the Claude app runs Claude Code, so a Nest chat starts and behaves the same (D047):
# answer before slow MCP servers finish connecting, connect them in batches, and keep old
# tool results in context instead of trimming them early.
CLAUDE_APP_ENV = {
    "MCP_CONNECTION_NONBLOCKING": "true",
    "MCP_SERVER_CONNECTION_BATCH_SIZE": "8",
    "DISABLE_MICROCOMPACT": "1",
}


class StderrTail:
    """What the CLI writes to stderr: each line goes to the daemon log (BUG-82), and the
    last ones say why it crashed (BUG-42).
    """

    def __init__(self, cwd: Path) -> None:
        self._cwd = cwd
        self._lines: deque[str] = deque(maxlen=STDERR_LINES)

    def add(self, line: str) -> None:
        text = line.strip()
        if text:
            stderr_logger.debug("Claude Code in %s: %s", self._cwd, scrub_credentials(text))
            self._lines.append(text)

    def text(self) -> str:
        """The last whole lines that fit in STDERR_CHARS, or the end of the last line."""
        kept: list[str] = []
        for line in reversed(self._lines):
            if kept and sum(len(k) + 1 for k in kept) + len(line) > STDERR_CHARS:
                break
            kept.append(line)
        text = scrub_credentials("\n".join(reversed(kept)))
        return text if len(text) <= STDERR_CHARS else "..." + text[3 - STDERR_CHARS :]


def build_options(
    spec: SessionSpec,
    handler: ApprovalHandler,
    gh_config_dir: Path,
    stderr: Callable[[str], None] | None = None,
    shell_env: Mapping[str, str] | None = None,
) -> ClaudeAgentOptions:
    """`shell_env` is the user's login shell environment (B59); Nest's own entries win."""
    questions = QuestionBridge(handler)
    own_tools = own_tool_names(spec.tools)

    async def can_use_tool(
        tool_name: str, tool_input: dict[str, JsonValue], context: ToolPermissionContext
    ) -> PermissionResult:
        if tool_name in own_tools:
            if context.agent_id is not None:
                return PermissionResultDeny(message=SUBAGENT_DENIED)
            return PermissionResultAllow()
        if tool_name == ASK_USER_QUESTION:
            return questions.permission(tool_input, context.tool_use_id)
        if tool_name == EXIT_PLAN_MODE:
            return await _review_plan(handler, tool_input, context.tool_use_id)
        reason = context.decision_reason or context.blocked_path
        updates, rule = always_updates(tool_name, tool_input, context.suggestions)
        decision = await handler.decide(
            PermissionRequest(tool_name, tool_input, context.title, reason, rule)
        )
        if decision.behavior == "allow":
            if decision.always:
                # Claude Code keeps suggested rules where it suggested: the session or a
                # settings file; Nest's own rule for the exact call, the session (B59).
                return PermissionResultAllow(updated_permissions=updates)
            return PermissionResultAllow()
        return PermissionResultDeny(message=decision.message or DEFAULT_DENY_MESSAGE)

    system_prompt: SystemPromptPreset = {"type": "preset", "preset": "claude_code"}
    if spec.system_prompt_append:
        system_prompt["append"] = spec.system_prompt_append
    # A guarded run checks every tool, so MCP and other shell tools are checked too (D049).
    pre_tool_use = [HookMatcher(matcher="*", hooks=[block_git_writes])] if spec.guard_git else []
    pre_tool_use.append(
        HookMatcher(
            matcher=ASK_USER_QUESTION,
            hooks=[questions.hook],
            timeout=QUESTION_TIMEOUT_SECONDS,
        )
    )
    if own_tools:
        pre_tool_use.append(
            HookMatcher(matcher="|".join(sorted(own_tools)), hooks=[subagent_guard(own_tools)])
        )
    if spec.write_root is not None:
        pre_tool_use.append(
            HookMatcher(matcher="|".join(WRITE_TOOLS), hooks=[write_guard(spec.write_root)])
        )
    return ClaudeAgentOptions(
        cwd=spec.cwd,
        model=spec.model,
        effort=spec.effort,
        permission_mode=spec.permission_mode,
        resume=spec.resume_id,
        # A cut conversation continues as a new session; the resumed one stays whole (B59).
        fork_session=spec.resume_at is not None,
        resume_session_at=spec.resume_at,
        resume_drops_turn=spec.drops_turn,
        add_dirs=list(spec.extra_dirs),
        system_prompt=system_prompt,
        # Load the user's own Claude Code setup: CLAUDE.md, skills, plugins, MCP, hooks.
        setting_sources=["user", "project", "local"],
        include_partial_messages=True,
        # Shown as in Claude Code (B59): what hooks say, subagents' text as they write it,
        # and thinking text, which newer models otherwise leave out.
        include_hook_events=True,
        forward_subagent_text=True,
        can_use_tool=can_use_tool,
        mcp_servers=tool_servers(spec.tools),
        allowed_tools=list(spec.allowed_tools),
        disallowed_tools=[*(GIT_WRITE_RULES if spec.guard_git else ()), *spec.disallowed_tools],
        # None keeps Claude Code's default of every skill.
        skills=list(spec.skills) or None,
        agents={name: _agent(sub, own_tools) for name, sub in spec.subagents.items()} or None,
        hooks={"PreToolUse": pre_tool_use},
        env={
            **(shell_env or {}),
            **(agent_env(gh_config_dir) if spec.guard_git else {}),
            **CLAUDE_APP_ENV,
        },
        stderr=stderr,
        max_buffer_size=MAX_MESSAGE_BYTES,
        # Files can be restored to before a user message; the echo of each message the
        # run is sent carries the id to restore to (IMP-02).
        enable_file_checkpointing=True,
        extra_args={"replay-user-messages": None, "thinking-display": "summarized"},
    )


class ClaudeRun:
    """One CLI process. A single reader consumes its output for the whole life of the run,
    so turns the agent starts on its own are reported like any other.
    """

    steers = True

    def __init__(self, client: SdkClient, sink: ProviderEventSink, stderr: StderrTail) -> None:
        self._client = client
        self._sink = sink
        self._stderr = stderr
        self._tasks = BackgroundTasks()
        self._thinking = ThinkingTimer()
        self._output = TurnOutput()
        self._reader = asyncio.create_task(self._read())

    async def send(self, user_input: UserInput) -> None:
        self._thinking.mark()
        self._output.awaiting_replay = True
        await self._client.query(_single(_user_message(user_input)))

    async def steer(self, user_input: UserInput, message_id: str) -> None:
        uuid = engine_uuid(message_id)
        # Its echo carries the uuid; known before the write, as the echo may come at once.
        self._output.steered[uuid] = message_id
        await self._client.query(_single({**_user_message(user_input), "uuid": uuid}))

    async def withdraw(self, message_id: str) -> bool:
        uuid = engine_uuid(message_id)
        if not await withdraw(self._client, uuid):
            return False
        self._output.steered.pop(uuid, None)
        return True

    async def interrupt(self) -> None:
        await self._client.interrupt()

    async def set_model(self, model: str | None) -> None:
        await self._client.set_model(model)

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        self._output.mode_set = True
        await self._client.set_permission_mode(mode)

    async def connector_statuses(self) -> list[McpServer]:
        status = await self._client.get_mcp_status()
        return mcp_servers(status.get("mcpServers"))

    async def context_usage(self) -> ContextUsage | None:
        return context_usage(await self._client.get_context_usage())

    async def rewind_files(self, checkpoint_id: str, dry_run: bool) -> RewindResult:
        return await rewind(self._client, checkpoint_id, dry_run)

    async def stop_task(self, task_id: str) -> bool:
        running = self._tasks.running(task_id)
        if running is None:
            return False
        await self._client.stop_task(running)
        return True

    async def close(self) -> None:
        self._reader.cancel()
        await asyncio.gather(self._reader, return_exceptions=True)
        # Closes stdin and waits for the CLI to exit, so its SessionEnd hooks have run.
        await self._client.disconnect()
        await self._abandon_tasks()

    async def _read(self) -> None:
        error = "the agent process ended"
        try:
            async for message in self._client.receive_messages():
                await self._handle(message)
        except Exception as exc:
            error = str(exc)
            tail = self._stderr.text()
            if tail:
                error = error.replace(STDERR_PLACEHOLDER, tail)
        with suppress(Exception):
            await self._client.disconnect()
        await self._abandon_tasks()
        await self._sink.stopped(error)

    async def _handle(self, message: Message) -> None:
        """One message; a failure here skips it instead of ending a healthy run (B-05)."""
        try:
            running = self._tasks.update(message)
            if running is not None:
                await self._sink.background_tasks(running)
            await translate(message, self._sink, self._thinking, self._output)
        except Exception as exc:
            logger.warning(
                "could not handle a message from the agent (%s: %s)", type(exc).__name__, exc
            )

    async def _abandon_tasks(self) -> None:
        """Background tasks live in the agent process and end with it."""
        for update in self._tasks.abandon():
            await self._sink.task(update)


class ClaudeProvider:
    name = "claude"

    def __init__(
        self,
        gh_config_dir: Path,
        client_factory: ClientFactory = ClaudeSDKClient,
        shell_env: ShellEnvSource = no_shell_env,
        claude_dir: Path | None = None,
    ) -> None:
        """`shell_env` gives each run the user's login shell environment (B59);
        `claude_dir` holds Claude Code's transcripts (None: none are read).
        """
        self._claude_dir = claude_dir
        self._gh_config_dir = gh_config_dir
        self._client_factory = client_factory
        self._shell_env = shell_env

    async def open(
        self, spec: SessionSpec, handler: ApprovalHandler, sink: ProviderEventSink
    ) -> ClaudeRun:
        stderr = StderrTail(spec.cwd)
        env = await self._shell_env()
        client = self._client_factory(
            build_options(spec, handler, self._gh_config_dir, stderr.add, env)
        )
        try:
            await client.connect()
            info = await client.get_server_info()
            catalog = described_catalog(info)
            if catalog is not None:
                await sink.commands(catalog)
            details = engine_details(info)
            if details is not None:
                await sink.engine_details(details)
        except BaseException:
            # Cancelled or failed after the CLI started: it must not run on unowned.
            with suppress(Exception):
                await client.disconnect()
            raise
        return ClaudeRun(client, sink, stderr)

    async def fork_point(self, cwd: Path, session_id: str, message_id: str) -> ForkPoint | None:
        if self._claude_dir is None:
            return None
        projects = self._claude_dir / "projects"
        return await asyncio.to_thread(fork_point, projects, cwd, session_id, message_id)


async def _review_plan(
    handler: ApprovalHandler, tool_input: dict[str, JsonValue], tool_use_id: str | None
) -> PermissionResult:
    """The plan goes to the user as a plan to approve; an approval may switch the mode."""
    plan = tool_input.get("plan")
    decision = await handler.review_plan(
        PlanRequest(plan if isinstance(plan, str) else "", tool_use_id)
    )
    if not decision.approved:
        return PermissionResultDeny(message=decision.message or KEEP_PLANNING_MESSAGE)
    if decision.mode is None:
        return PermissionResultAllow()
    return PermissionResultAllow(
        updated_permissions=[
            PermissionUpdate(type="setMode", mode=decision.mode, destination="session")
        ]
    )


def _agent(subagent: Subagent, own_tools: frozenset[str]) -> AgentDefinition:
    """The run's own tools are never the subagent's (B41)."""
    denied = [*subagent.disallowed_tools, *sorted(own_tools)]
    return AgentDefinition(
        description=subagent.description,
        prompt=subagent.prompt,
        model=subagent.model,
        effort=subagent.effort,
        skills=list(subagent.skills) or None,
        permissionMode=subagent.permission_mode,
        disallowedTools=denied or None,
    )


def _user_message(user_input: UserInput) -> dict[str, Any]:
    text = user_input.text
    if user_input.file_paths:
        listing = "\n".join(f"- {path}" for path in user_input.file_paths)
        text = f"{text}\n\nAttached files:\n{listing}"
    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": image.media_type, "data": image.data},
        }
        for image in user_input.images
    ]
    content.append({"type": "text", "text": text})
    return {
        "type": "user",
        "message": {"role": "user", "content": content},
        "parent_tool_use_id": None,
    }


async def _single(message: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    yield message
