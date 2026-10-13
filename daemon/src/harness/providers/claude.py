"""Claude provider on the Claude Agent SDK (D003), with the agent git block layers (D013)."""

import asyncio
import logging
from collections import deque
from collections.abc import AsyncIterable, AsyncIterator, Callable
from contextlib import suppress
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import (
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

from harness.config.models import PermissionMode
from harness.gitops.remotes import scrub_credentials
from harness.logging_setup import ENGINE_STDERR_LOGGER
from harness.providers.base import (
    ApprovalHandler,
    ContextUsage,
    McpServer,
    PermissionRequest,
    PlanRequest,
    ProviderEventSink,
    RewindResult,
    SessionSpec,
    UserInput,
)
from harness.providers.claude_commands import context_usage, described_catalog
from harness.providers.claude_engine import engine_details
from harness.providers.claude_messages import (
    BackgroundTasks,
    TurnOutput,
    mcp_servers,
    translate,
)
from harness.providers.claude_questions import (
    ASK_USER_QUESTION,
    QUESTION_TIMEOUT_SECONDS,
    QuestionBridge,
)
from harness.providers.claude_rewind import rewind
from harness.providers.claude_rules import always_rule
from harness.providers.claude_thinking import ThinkingTimer
from harness.providers.git_guard import GIT_WRITE_RULES, block_git_writes

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

    async def get_context_usage(self) -> ContextUsageResponse: ...

    async def get_server_info(self) -> dict[str, Any] | None: ...

    async def disconnect(self) -> None: ...


type ClientFactory = Callable[[ClaudeAgentOptions], SdkClient]


def agent_env(gh_config_dir: Path) -> dict[str, str]:
    """Layer 3: no git credential helpers, prompts or GitHub token for the agent."""
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


# How the Claude app runs Claude Code, so a harness chat starts and behaves the same (D047):
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
) -> ClaudeAgentOptions:
    questions = QuestionBridge(handler)

    async def can_use_tool(
        tool_name: str, tool_input: dict[str, JsonValue], context: ToolPermissionContext
    ) -> PermissionResult:
        if tool_name == ASK_USER_QUESTION:
            return questions.permission(tool_input, context.tool_use_id)
        if tool_name == EXIT_PLAN_MODE:
            return await _review_plan(handler, tool_input, context.tool_use_id)
        reason = context.decision_reason or context.blocked_path
        rule = always_rule(context.suggestions)
        decision = await handler.decide(
            PermissionRequest(tool_name, tool_input, context.title, reason, rule)
        )
        if decision.behavior == "allow":
            if decision.always and rule is not None:
                # Claude Code keeps them where it suggested: the session or a settings file.
                return PermissionResultAllow(updated_permissions=list(context.suggestions))
            return PermissionResultAllow()
        return PermissionResultDeny(message=decision.message or DEFAULT_DENY_MESSAGE)

    system_prompt: SystemPromptPreset = {"type": "preset", "preset": "claude_code"}
    if spec.system_prompt_append:
        system_prompt["append"] = spec.system_prompt_append
    return ClaudeAgentOptions(
        cwd=spec.cwd,
        model=spec.model,
        effort=spec.effort,
        permission_mode=spec.permission_mode,
        resume=spec.resume_id,
        add_dirs=list(spec.extra_dirs),
        system_prompt=system_prompt,
        # Load the user's own Claude Code setup: CLAUDE.md, skills, plugins, MCP, hooks.
        setting_sources=["user", "project", "local"],
        include_partial_messages=True,
        can_use_tool=can_use_tool,
        disallowed_tools=list(GIT_WRITE_RULES),
        hooks={
            "PreToolUse": [
                HookMatcher(matcher="*", hooks=[block_git_writes]),
                HookMatcher(
                    matcher=ASK_USER_QUESTION,
                    hooks=[questions.hook],
                    timeout=QUESTION_TIMEOUT_SECONDS,
                ),
            ]
        },
        env={**agent_env(gh_config_dir), **CLAUDE_APP_ENV},
        stderr=stderr,
        max_buffer_size=MAX_MESSAGE_BYTES,
        # Files can be restored to before a user message; the echo of each message the
        # run is sent carries the id to restore to (IMP-02).
        enable_file_checkpointing=True,
        extra_args={"replay-user-messages": None},
    )


class ClaudeRun:
    """One CLI process. A single reader consumes its output for the whole life of the run,
    so turns the agent starts on its own are reported like any other.
    """

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

    async def interrupt(self) -> None:
        await self._client.interrupt()

    async def set_model(self, model: str | None) -> None:
        await self._client.set_model(model)

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        await self._client.set_permission_mode(mode)

    async def connector_statuses(self) -> list[McpServer]:
        status = await self._client.get_mcp_status()
        return mcp_servers(status.get("mcpServers"))

    async def context_usage(self) -> ContextUsage | None:
        return context_usage(await self._client.get_context_usage())

    async def rewind_files(self, checkpoint_id: str, dry_run: bool) -> RewindResult:
        return await rewind(self._client, checkpoint_id, dry_run)

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
        self, gh_config_dir: Path, client_factory: ClientFactory = ClaudeSDKClient
    ) -> None:
        self._gh_config_dir = gh_config_dir
        self._client_factory = client_factory

    async def open(
        self, spec: SessionSpec, handler: ApprovalHandler, sink: ProviderEventSink
    ) -> ClaudeRun:
        stderr = StderrTail(spec.cwd)
        client = self._client_factory(build_options(spec, handler, self._gh_config_dir, stderr.add))
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
