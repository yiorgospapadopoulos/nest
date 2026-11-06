"""Engines on the Agent Client Protocol as Nest chats (B107): OpenCode, Gemini CLI and the
untested Cursor agent, one `AcpProvider` per engine (`acp_engines`).

Each run is one engine process with one ACP session: new, or reopened by the session id
Nest keeps as the session's provider session id, with `session/resume` where the engine
has it and else `session/load`, whose replay is dropped. Each user message is a
`session/prompt`, which answers when the turn ends; a Stop is `session/cancel`. The model
and the engine's plan mode are set on the session, so a change applies from the next
message. Messages written during a turn wait for its end (`steers` is False).

Nest decides every permission request itself (`acp_permissions`) and serves the engine's
file reads and writes (`acp_fs`). A run's Nest tools (a pixie's memory, artifacts, calling
pixies) are served by `ToolHost` and given to the engine as HTTP MCP servers; an engine
without HTTP MCP cannot take them. ACP has no system prompt: a new session's first
message starts with Nest's instructions, a pixie's skill list and the tools hint as a
block of its own, which the transcript does not show (only the engine's replies are).

ACP has no request for questions to the user, so a run on an engine with HTTP MCP also
gets Nest's `ask_user` (`acp_questions`, B112). The engine's plan is the chat's task list
(`acp_events`). A pixie's skill list cannot limit the engine's skills: the first message
names them, which the engine may not keep to (B112, a recorded limitation), so a pixie on
it keeps its list and `pixie_skills` is not reported unsupported. The only tasks an ACP
chat shows are the pixies it called, which the session manager stops by their call, not
the engine (B112), so Stop is offered.

What only Claude does is reported unsupported (`ACP_UNSUPPORTED`): rewinding, forking,
taking back a message, plan review, `#` memory outside a pixie's chat (the composer
writes a pixie's own memory on every engine).
"""

import asyncio
import json
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import get_args

from pydantic import JsonValue

from nestd import __version__
from nestd.config.models import Effort, PermissionMode
from nestd.errors import ConflictError
from nestd.providers.acp_engines import AcpEngine
from nestd.providers.acp_events import AcpStream, NestTools
from nestd.providers.acp_fs import AcpFiles
from nestd.providers.acp_permissions import AcpPermissions, AcpRules
from nestd.providers.acp_process import AcpLaunch, AcpTransportFactory, spawn_acp
from nestd.providers.acp_questions import ask_user_tool
from nestd.providers.acp_rpc import (
    AUTH_REQUIRED,
    METHOD_NOT_FOUND,
    AcpClosedError,
    AcpRpc,
    AcpRpcError,
    JsonObject,
)
from nestd.providers.base import (
    AgentTool,
    ApprovalHandler,
    ContextUsage,
    ForkPoint,
    McpServer,
    ModelOption,
    ProviderEventSink,
    ProviderFeature,
    RewindResult,
    RunAccount,
    SessionSpec,
    UserInput,
)
from nestd.providers.claude_tools import NEST_SERVER, TOOL_SERVER
from nestd.providers.codex_items import items, obj, text
from nestd.providers.codex_tools import ToolHost
from nestd.providers.git_guard import NO_PUSH_ENV
from nestd.providers.shell_env import ShellEnvSource, no_shell_env

__all__ = [
    "ACP_UNSUPPORTED",
    "DEFAULT_MODEL",
    "AcpLaunch",
    "AcpLauncher",
    "AcpNotReadyError",
    "AcpProbe",
    "AcpProbeError",
    "AcpProvider",
    "AcpRun",
    "AcpToolsUnsupportedError",
    "AcpTransportFactory",
    "probe",
    "spawn_acp",
]

logger = logging.getLogger(__name__)

ACP_UNSUPPORTED: frozenset[ProviderFeature] = frozenset(
    {
        "rewind",
        "fork",
        "withdraw",
        "plan_review",
        "memory",
    }
)
# The model a chat without a model uses: the engine's own default (left as it is).
DEFAULT_MODEL = "default"
PROTOCOL_VERSION = 1
PROBE_TIMEOUT = timedelta(seconds=60)
PLAN_MODE = "plan"
_EFFORTS: frozenset[str] = frozenset(get_args(Effort))
# How engines word a missing sign-in when they do not use ACP's code for it.
_AUTH_WORDS = re.compile(r"api key|auth|sign(?:ed)? ?in|log(?:ged)? ?in|credential", re.I)

# Builds the engine's command and environment for an account (the engine service's);
# raises AcpNotReadyError when the engine cannot start.
type AcpLauncher = Callable[[RunAccount | None], Awaitable[AcpLaunch]]


# The title an engine gives a session before it has named it.
_PLACEHOLDER_TITLE = re.compile(r"new session\b", re.IGNORECASE)


class AcpNotReadyError(ConflictError):
    """The engine cannot run: not installed, without its key, or signed out."""

    code = "engine_not_ready"

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "code": self.code}


class AcpToolsUnsupportedError(ConflictError):
    """The engine has no HTTP MCP servers, which Nest's tools for a run need."""

    code = "unsupported_feature"

    def __init__(self, engine: AcpEngine) -> None:
        self.provider = engine.id
        self.feature = "pixies"
        super().__init__(
            f"{engine.name} cannot take Nest's tools (it has no HTTP MCP servers), "
            "so it cannot run pixies or Nest's tools."
        )

    def payload(self) -> dict[str, JsonValue]:
        return {
            "detail": str(self),
            "code": self.code,
            "provider": self.provider,
            "feature": self.feature,
        }


class AcpProbeError(Exception):
    """The engine could not be asked; the message never quotes what it printed."""


@dataclass(frozen=True)
class AcpProbe:
    # The engine's default first, as "default"; empty when it is not signed in.
    models: list[ModelOption]
    # False when the engine asked for a sign-in before opening a session.
    signed_in: bool | None
    agent_version: str | None
    mcp_http: bool


@dataclass(frozen=True)
class AgentCaps:
    """What `initialize` says the engine can do."""

    name: str
    version: str | None
    load: bool
    resume: bool
    close: bool
    mcp_http: bool
    image: bool
    # The engine lists its sessions with their titles (`session/list`).
    list_sessions: bool = False


@dataclass(frozen=True)
class SessionOptions:
    """A session's models, modes and thinking levels, as config options (OpenCode) or the
    older `models` and `modes` objects (Gemini).
    """

    # The config option that picks the model; None with `models` or neither.
    model_option: str | None = None
    legacy_models: bool = False
    model: str | None = None
    # (value, name, description) in the engine's order.
    models: tuple[tuple[str, str, str], ...] = ()
    mode_option: str | None = None
    legacy_modes: bool = False
    mode: str | None = None
    modes: tuple[str, ...] = ()
    thought_option: str | None = None
    thought_levels: tuple[str, ...] = ()

    def can_set_model(self) -> bool:
        return self.model_option is not None or self.legacy_models


def agent_caps(result: JsonObject) -> AgentCaps:
    caps = obj(result.get("agentCapabilities"))
    sessions = obj(caps.get("sessionCapabilities"))
    info = obj(result.get("agentInfo"))
    return AgentCaps(
        name=text(info.get("title")) or text(info.get("name")) or "The engine",
        version=text(info.get("version")) or None,
        load=caps.get("loadSession") is True,
        resume=sessions.get("resume") not in (None, False),
        close=sessions.get("close") not in (None, False),
        mcp_http=obj(caps.get("mcpCapabilities")).get("http") is True,
        image=obj(caps.get("promptCapabilities")).get("image") is True,
        list_sessions=sessions.get("list") not in (None, False),
    )


def session_options(result: JsonObject) -> SessionOptions:
    configs = [obj(option) for option in items(result.get("configOptions"))]
    model, mode = _config(configs, "model"), _config(configs, "mode")
    thought = next((c for c in configs if c.get("category") == "thought_level"), None)
    legacy_models, legacy_modes = obj(result.get("models")), obj(result.get("modes"))
    models = (
        _choices(model)
        if model is not None
        else [
            (value, text(entry.get("name")) or value, text(entry.get("description")))
            for entry in (obj(e) for e in items(legacy_models.get("availableModels")))
            if (value := text(entry.get("modelId")))
        ]
    )
    modes = (
        [value for value, _, _ in _choices(mode)]
        if mode is not None
        else [
            value
            for entry in items(legacy_modes.get("availableModes"))
            if (value := text(obj(entry).get("id")))
        ]
    )
    return SessionOptions(
        model_option=text(model.get("id")) if model is not None else None,
        legacy_models=model is None and bool(legacy_models),
        model=(
            text(model.get("currentValue"))
            if model is not None
            else text(legacy_models.get("currentModelId"))
        )
        or None,
        models=tuple(models),
        mode_option=text(mode.get("id")) if mode is not None else None,
        legacy_modes=mode is None and bool(legacy_modes),
        mode=(
            text(mode.get("currentValue"))
            if mode is not None
            else text(legacy_modes.get("currentModeId"))
        )
        or None,
        modes=tuple(modes),
        thought_option=text(thought.get("id")) if thought is not None else None,
        thought_levels=tuple(v for v, _, _ in _choices(thought or {}) if v in _EFFORTS),
    )


def acp_models(options: SessionOptions, engine_name: str) -> list[ModelOption]:
    """The session's models in the engine's order, after a `default` entry for the model
    the engine picks itself (the current one of a new session), as Claude's list has (D038).
    """
    levels = list(options.thought_levels)
    listed = [
        ModelOption(
            value=value,
            display_name=name,
            description=description,
            effort_levels=levels,
            supports_effort=bool(levels),
            resolved_model=value,
        )
        for value, name, description in options.models
    ]
    current = next((m for m in listed if m.value == options.model), None)
    if current is None:
        return listed
    default = current.model_copy(
        update={
            "value": DEFAULT_MODEL,
            "display_name": f"Default ({current.display_name})",
            "description": f"{engine_name}'s default model",
        }
    )
    return [default, *listed]


def engine_message(error: AcpRpcError) -> str:
    """The engine's words for an error, out of the JSON some wrap them in (Gemini's)."""
    details = obj(error.data).get("details") if isinstance(error.data, dict) else None
    message = details if isinstance(details, str) and details else error.message
    for _ in range(4):
        try:
            parsed: JsonValue = json.loads(message)
        except ValueError:
            return message
        inner = obj(obj(parsed).get("error")).get("message")
        if not isinstance(inner, str) or not inner:
            return message
        message = inner
    return message


def auth_required(error: AcpRpcError) -> bool:
    return error.code == AUTH_REQUIRED or bool(_AUTH_WORDS.search(engine_message(error)))


async def initialize(rpc: AcpRpc) -> AgentCaps:
    """The handshake: Nest serves text file reads and writes, and no terminals."""
    result = await rpc.request(
        "initialize",
        {
            "protocolVersion": PROTOCOL_VERSION,
            "clientCapabilities": {
                "fs": {"readTextFile": True, "writeTextFile": True},
                "terminal": False,
            },
            "clientInfo": {"name": "nest", "title": "Nest", "version": __version__},
        },
    )
    return agent_caps(result)


class AcpRun:
    steers = False

    def __init__(
        self,
        engine: AcpEngine,
        spec: SessionSpec,
        handler: ApprovalHandler,
        sink: ProviderEventSink,
    ) -> None:
        """The run serves its Nest tools from `start` until it closes."""
        self._engine = engine
        self._spec = spec
        self._handler = handler
        self._sink = sink
        self._tools: ToolHost | None = None
        self._served = _served(spec)
        self._nest = _nest_tools(self._served)
        self._model = spec.model
        self._mode: PermissionMode | None = spec.permission_mode
        self.stream = AcpStream(sink, self._nest)
        self._permissions = AcpPermissions(handler, self.rules, self.stream)
        self._files = AcpFiles(self.rules)
        self._rpc: AcpRpc | None = None
        self._session_id: str | None = None
        self._caps: AgentCaps | None = None
        self._options = SessionOptions()
        # The engine's own default model, known for a new session only.
        self._default_model: str | None = None
        self._engine_model: str | None = None
        self._normal_mode: str | None = None
        self._engine_mode: str | None = None
        # Nest's instructions go before the first message of a new session.
        self._lead_pending = spec.resume_id is None
        self._prompting = False
        self._turns: set[asyncio.Task[None]] = set()

    def rules(self) -> AcpRules:
        spec = self._spec
        folders = (spec.cwd, *spec.extra_dirs)
        return AcpRules(
            self._mode,
            spec.guard_git,
            folders,
            spec.write_root,
            self._nest,
            worktrees=spec.guard_worktrees,
        )

    @property
    def rpc(self) -> AcpRpc:
        assert self._rpc is not None  # noqa: S101 (set when the run starts)
        return self._rpc

    @property
    def session_id(self) -> str:
        assert self._session_id is not None  # noqa: S101 (set once the session is open)
        return self._session_id

    async def start(self, rpc: AcpRpc) -> None:
        """The handshake and the session; the run is usable once this returns."""
        self._rpc = rpc
        caps = await initialize(rpc)
        self._caps = caps
        await self._serve_tools(caps)
        servers = self._tools.acp_servers() if self._tools is not None else []
        session_id, result = await self._open_session(caps, servers)
        self.stream.session_id = session_id
        options = session_options(result)
        self._options = options
        self._engine_model = options.model
        if self._spec.resume_id is None:
            self._default_model = options.model
        self._engine_mode = options.mode
        if PLAN_MODE in options.modes:
            self._normal_mode = _normal_mode(options)
        try:
            await self._apply_model(self._model)
            await self._apply_effort()
        except AcpRpcError as error:
            # The chat runs on the engine's choice rather than not at all.
            logger.warning("%s refused the model or thinking level (%s)", self._engine.name, error)
        self._session_id = session_id
        await self._sink.provider_session_id(session_id)

    @property
    def names_chats(self) -> bool:
        return self._caps is not None and self._caps.list_sessions

    async def engine_title(self, session_id: str) -> str | None:
        """The session's title in the engine's list, unless it is still the engine's
        placeholder (OpenCode's `New session - <time>`).
        """
        listed = await self.rpc.request("session/list", {"cwd": str(self._spec.cwd)})
        for entry in items(listed.get("sessions")):
            session = obj(entry)
            if text(session.get("sessionId")) == session_id:
                title = text(session.get("title"))
                return None if _PLACEHOLDER_TITLE.match(title) else title or None
        return None

    async def on_request(self, method: str, params: JsonObject) -> JsonValue:
        if method == "session/request_permission":
            return await self._permissions.handle(params)
        if method == "fs/read_text_file":
            return await self._files.read(params)
        if method == "fs/write_text_file":
            return await self._files.write(params)
        msg = f"Nest does not answer {method}"
        raise AcpRpcError(METHOD_NOT_FOUND, msg)

    async def closed(self, reason: str) -> None:
        """The engine ended on its own, and with it the run's tools; while the run opens,
        opening fails instead.
        """
        if self._session_id is not None:
            if self._tools is not None:
                await self._tools.close()
            await self._sink.stopped(reason)

    async def send(self, user_input: UserInput) -> None:
        await self._sync_mode()
        prompt = self._prompt(user_input)
        self._prompting = True
        task = asyncio.create_task(self._turn(prompt))
        self._turns.add(task)
        task.add_done_callback(self._turns.discard)

    async def steer(self, user_input: UserInput, message_id: str) -> None:
        msg = f"{self._engine.name} takes no message into a running turn"
        raise RuntimeError(msg)

    async def withdraw(self, message_id: str) -> bool:
        """Nothing is ever written into a turn, so a waiting message is Nest's to keep."""
        return True

    async def interrupt(self) -> None:
        if self._prompting:
            self._permissions.cancel_pending()
            await self.rpc.notify("session/cancel", {"sessionId": self.session_id})

    async def set_model(self, model: str | None) -> None:
        self._model = model
        try:
            await self._apply_model(model)
        except AcpRpcError as error:
            logger.warning("%s refused the model %s (%s)", self._engine.name, model, error)

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        self._mode = mode

    async def connector_statuses(self) -> list[McpServer]:
        return []

    async def context_usage(self) -> ContextUsage | None:
        return self.stream.context_usage()

    async def rewind_files(self, checkpoint_id: str, dry_run: bool) -> RewindResult:
        return RewindResult(
            can_rewind=False,
            error=f"{self._engine.name} chats cannot restore files to before a message.",
        )

    async def stop_task(self, task_id: str) -> bool:
        """The engine runs no task of its own Nest could stop; a called pixie is stopped
        by the session manager (B112).
        """
        return False

    async def close(self) -> None:
        try:
            await self.rpc.close()
            await asyncio.gather(*self._turns, return_exceptions=True)
        finally:
            await self.close_tools()

    async def close_tools(self) -> None:
        if self._tools is not None:
            await self._tools.close()

    async def _serve_tools(self, caps: AgentCaps) -> None:
        """The run's Nest tools, with `ask_user` on an engine that takes HTTP MCP servers;
        an engine without them runs only without Nest's other tools.
        """
        if self._served and not caps.mcp_http:
            raise AcpToolsUnsupportedError(self._engine)
        if not caps.mcp_http:
            return
        ask = ask_user_tool(self._handler, self._engine.mcp_tool_timeout)
        served = {**self._served, NEST_SERVER: (*self._served.get(NEST_SERVER, ()), ask)}
        self._tools = await ToolHost.start(served)
        self._served = served
        self._nest = _nest_tools(served)
        self.stream.nest = self._nest

    async def _open_session(
        self, caps: AgentCaps, servers: list[JsonValue]
    ) -> tuple[str, JsonObject]:
        spec = self._spec
        params: JsonObject = {"cwd": str(spec.cwd), "mcpServers": servers}
        try:
            if spec.resume_id is None:
                result = await self.rpc.request("session/new", params)
                return text(result.get("sessionId")), result
            params["sessionId"] = spec.resume_id
            if caps.resume:
                return spec.resume_id, await self.rpc.request("session/resume", params)
            if not caps.load:
                msg = f"{self._engine.name} cannot reopen an earlier chat."
                raise ConflictError(msg)
            # The engine replays the history before it answers; Nest has it already.
            self.stream.replaying = True
            try:
                return spec.resume_id, await self.rpc.request("session/load", params)
            finally:
                self.stream.replaying = False
        except AcpRpcError as error:
            if auth_required(error):
                raise AcpNotReadyError(engine_message(error)) from error
            raise

    async def _apply_model(self, model: str | None) -> None:
        options = self._options
        value = model if model and model != DEFAULT_MODEL else self._default_model
        if value is None or value == self._engine_model or not options.can_set_model():
            return
        if options.model_option is not None:
            await self.rpc.request(
                "session/set_config_option",
                {
                    "sessionId": self.stream.session_id,
                    "configId": options.model_option,
                    "value": value,
                },
            )
        else:
            await self.rpc.request(
                "session/set_model", {"sessionId": self.stream.session_id, "modelId": value}
            )
        self._engine_model = value

    async def _apply_effort(self) -> None:
        options = self._options
        effort = self._spec.effort
        if options.thought_option is None or effort not in options.thought_levels:
            return
        await self.rpc.request(
            "session/set_config_option",
            {
                "sessionId": self.stream.session_id,
                "configId": options.thought_option,
                "value": effort,
            },
        )

    async def _sync_mode(self) -> None:
        """The engine's plan mode follows Nest's permission mode, from the next message."""
        options = self._options
        if self._normal_mode is None:
            return
        wanted = PLAN_MODE if self._mode == "plan" else self._normal_mode
        if wanted == self._engine_mode:
            return
        try:
            if options.mode_option is not None:
                await self.rpc.request(
                    "session/set_config_option",
                    {
                        "sessionId": self.session_id,
                        "configId": options.mode_option,
                        "value": wanted,
                    },
                )
            else:
                await self.rpc.request(
                    "session/set_mode", {"sessionId": self.session_id, "modeId": wanted}
                )
        except AcpRpcError as error:
            logger.warning("%s refused the mode %s (%s)", self._engine.name, wanted, error)
            return
        self._engine_mode = wanted

    def _prompt(self, user_input: UserInput) -> list[JsonValue]:
        blocks: list[JsonValue] = []
        if self._lead_pending:
            self._lead_pending = False
            parts = (
                self._spec.system_prompt_append,
                skills_line(self._spec.skills),
                _tools_hint(self._served),
            )
            lead = "\n\n".join(part for part in parts if part)
            if lead:
                blocks.append({"type": "text", "text": lead})
        message = user_input.text
        if user_input.file_paths:
            listing = "\n".join(f"- {path}" for path in user_input.file_paths)
            message = f"{message}\n\nAttached files:\n{listing}"
        if self._caps is not None and self._caps.image:
            for image in user_input.images:
                blocks.append({"type": "image", "mimeType": image.media_type, "data": image.data})
        elif user_input.images:
            left_out = f"{len(user_input.images)} attached images were left out"
            message = f"{message}\n\n({left_out}: {self._engine.name} takes no images.)"
        blocks.append({"type": "text", "text": message})
        return blocks

    async def _turn(self, prompt: list[JsonValue]) -> None:
        started = time.monotonic()
        try:
            try:
                result = await self.rpc.request(
                    "session/prompt", {"sessionId": self.session_id, "prompt": prompt}
                )
            except AcpClosedError:
                return  # the run stopped, which the sink hears from `closed`
            except AcpRpcError as error:
                self._prompting = False
                await self.stream.failed(engine_message(error), _since(started))
                return
            self._prompting = False
            await self.stream.finished(result, _since(started))
        except Exception:
            logger.exception("%s's turn could not be reported", self._engine.name)
        finally:
            self._prompting = False


class AcpProvider:
    def __init__(
        self,
        engine: AcpEngine,
        launcher: AcpLauncher,
        transport: AcpTransportFactory = spawn_acp,
        shell_env: ShellEnvSource = no_shell_env,
    ) -> None:
        self._engine = engine
        self._launcher = launcher
        self._transport = transport
        self._shell_env = shell_env

    @property
    def name(self) -> str:
        return self._engine.id

    @property
    def unsupported(self) -> frozenset[ProviderFeature]:
        return ACP_UNSUPPORTED

    async def open(
        self, spec: SessionSpec, handler: ApprovalHandler, sink: ProviderEventSink
    ) -> AcpRun:
        launch = await self._launcher(spec.account)
        run = AcpRun(self._engine, spec, handler, sink)
        extra = {
            **spec.env,
            **(NO_PUSH_ENV if spec.guard_git else {}),
            **(self._engine.guarded_env if spec.nest_decides else {}),
        }
        env = process_env(await self._shell_env(), launch.env, extra)
        transport = await self._transport(AcpLaunch(launch.args, env), spec.cwd)
        rpc = AcpRpc(
            transport, run.stream.handle, run.on_request, run.closed, peer=self._engine.name
        )
        try:
            await run.start(rpc)
        except BaseException:
            await rpc.close()
            await run.close_tools()
            raise
        return run

    async def fork_point(self, cwd: Path, session_id: str, message_id: str) -> ForkPoint | None:
        """ACP chats are not forked or rewound (ACP_UNSUPPORTED)."""
        return None


async def probe(
    launch: AcpLaunch,
    cwd: Path,
    transport: AcpTransportFactory = spawn_acp,
    time_limit: timedelta = PROBE_TIMEOUT,
) -> AcpProbe:
    """The engine's models and whether it is signed in, from a session opened in `cwd`
    (a Nest-owned scratch folder) without a prompt, so no model is called. The session is
    closed where the engine can, and the process ended.
    """

    async def ignore(_method: str, _params: JsonObject) -> None:
        return None

    async def refuse(method: str, _params: JsonObject) -> JsonValue:
        raise AcpRpcError(METHOD_NOT_FOUND, f"Nest does not answer {method} here")

    try:
        async with asyncio.timeout(time_limit.total_seconds()):
            rpc = AcpRpc(await transport(launch, cwd), ignore, refuse)
            try:
                caps = await initialize(rpc)
                try:
                    result = await rpc.request("session/new", {"cwd": str(cwd), "mcpServers": []})
                except AcpRpcError as error:
                    if not auth_required(error):
                        raise
                    return AcpProbe([], False, caps.version, caps.mcp_http)
                session_id = text(result.get("sessionId"))
                if caps.close and session_id:
                    with suppress(AcpRpcError):
                        await rpc.request("session/close", {"sessionId": session_id})
                models = acp_models(session_options(result), caps.name)
                return AcpProbe(models, True, caps.version, caps.mcp_http)
            finally:
                await rpc.close()
    except TimeoutError as error:
        msg = "timed out"
        raise AcpProbeError(msg) from error
    except Exception as error:
        # The engine's errors can quote what it printed; only their kind is kept.
        raise AcpProbeError(type(error).__name__) from error


def process_env(
    shell: Mapping[str, str], launch: Mapping[str, str], extra: Mapping[str, str]
) -> dict[str, str]:
    """The engine's environment: the launcher's over the user's login shell's, so the
    engine's own settings and the account's folder win, with the shell's PATH entries
    after the launcher's (the engine finds the user's tools, such as node); `extra` (the
    chat's ports, a guarded run's git-level push block) over all.
    """
    env = {**shell, **launch}
    if (shell_path := shell.get("PATH")) and (launch_path := launch.get("PATH")):
        entries = [*launch_path.split(os.pathsep), *shell_path.split(os.pathsep)]
        env["PATH"] = os.pathsep.join(dict.fromkeys(e for e in entries if e))
    env.update(extra)
    return env


type Served = Mapping[str, tuple[AgentTool, ...]]


def _served(spec: SessionSpec) -> dict[str, tuple[AgentTool, ...]]:
    """Nest's MCP servers for the run that have tools, named as Claude's runs have them
    (`claude_tools`).
    """
    servers = {TOOL_SERVER: spec.tools, NEST_SERVER: spec.nest_tools}
    return {name: tools for name, tools in servers.items() if tools}


def _nest_tools(served: Served) -> NestTools:
    return {server: frozenset(tool.name for tool in tools) for server, tools in served.items()}


def skills_line(skills: tuple[str, ...]) -> str:
    """A pixie's skill list as a line of its first message: ACP has no per-run skill list,
    so the engine is only asked to keep to it (B112); empty leaves every skill.
    """
    if not skills:
        return ""
    return f"Use only these skills in this chat: {', '.join(skills)}. Leave any other skill alone."


def _tools_hint(served: Served) -> str:
    """A line naming the run's Nest tools, which the model may not find among the user's
    many MCP tools on its own; empty without any.
    """
    groups = [
        ", ".join(tool.name for tool in tools) + f" (the {server} MCP server)"
        for server, tools in served.items()
    ]
    if not groups:
        return ""
    return f"Nest's tools for this chat are MCP tools: {' and '.join(groups)}."


def _config(configs: list[JsonObject], name: str) -> JsonObject | None:
    return next((c for c in configs if c.get("category") == name or c.get("id") == name), None)


def _choices(option: JsonObject) -> list[tuple[str, str, str]]:
    """A select option's values, names and descriptions; grouped ones flattened."""
    found: list[tuple[str, str, str]] = []
    for entry in (obj(e) for e in items(option.get("options"))):
        if "options" in entry:
            found += _choices(entry)
        elif value := text(entry.get("value")):
            found.append((value, text(entry.get("name")) or value, text(entry.get("description"))))
    return found


def _normal_mode(options: SessionOptions) -> str | None:
    """The mode to leave plan mode for: the session's own, else the engine's default."""
    if options.mode is not None and options.mode != PLAN_MODE:
        return options.mode
    if "default" in options.modes:
        return "default"
    return next((mode for mode in options.modes if mode != PLAN_MODE), None)


def _since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
