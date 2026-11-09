"""An ACP engine's permission requests, decided by Nest (B107).

Nest makes each engine ask before every shell command, edit and outside-folder access
(`acp_engines`), and judges each request in this order:

1. A guarded run's git write, a subagent's while agents may not push where the engine
   marks a subagent's calls (Copilot, B153), and on Autopilot a worktree removal, is
   rejected without asking, in every mode (D013): the command (its input, else the title
   Gemini puts it in), and for an MCP tool its name and input, with the matchers the Claude
   side uses. OpenCode
   asks about an MCP tool before it says the tool's input, so a guarded run also rejects an
   MCP tool that comes without its input and whose name says it runs commands (`shell`,
   `exec`, `command`...), since its command cannot be read. The transcript shows Nest's
   reason as the result. With the user letting agents push no run is guarded (D160).
2. A run with a write root (a pixie's, D072) has every edit outside it rejected.
3. Nest's own MCP tools (`nest`, `pixie`) are allowed: they check their callers.
4. The chat's permission mode: `bypassPermissions` and `auto` allow the rest; a read or
   search is allowed in every mode when it names paths and all of them are inside the
   chat's folders (its own and its extra folders); `acceptEdits` allows edits inside
   them. Whatever is left asks the user, in plan mode too (the engine's own plan mode
   keeps it from editing): a read or search without a path Nest recognises, or with one
   outside, a fetch (as Claude Code's WebFetch asks), thinking and any other tool. Nest
   fails closed: what it cannot judge is asked.

Nest answers only with an option that allows or rejects once, never one that allows
always, after which the engine would stop asking. The user's "Always allow" is kept by
Nest for the run instead: a command by its exact text, edits by their kind, any other
tool by name. A Stop (`cancel_pending`) answers the questions still waiting as cancelled.
"""

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.providers.acp_events import (
    EDIT_KINDS,
    LOOK_KINDS,
    READ_KINDS,
    AcpStream,
    NestTools,
    ToolCall,
    command_text,
    mcp_call,
    paths,
    shell_call,
    title_name,
    tool_use,
    unknown_kind,
)
from nestd.providers.acp_rpc import JsonObject
from nestd.providers.base import ApprovalHandler, PermissionDecision, PermissionRequest
from nestd.providers.codex_items import items, obj, text
from nestd.providers.git_guard import (
    DENY_REASON,
    WORKTREE_DENY_REASON,
    is_git_write,
    tool_writes,
)

logger = logging.getLogger(__name__)

type Verdict = Literal["allow", "reject", "cancelled"]

_ALLOW_ONCE = ("once", "allow_once", "allow-once", "proceed_once")
_REJECT_ONCE = ("reject", "reject_once", "reject-once", "cancel")
_CANCELLED: JsonValue = {"outcome": {"outcome": "cancelled"}}
OUTSIDE_ROOT = "Nest: this run may change files only in {root}"
# An MCP tool name, in lowercase letters only, that says the tool runs commands.
_RUNS_COMMANDS = re.compile(r"shell|exec|command|terminal|bash|script|process|spawn|runcmd")


@dataclass(frozen=True)
class AcpRules:
    """What a run's decisions depend on, read when each request comes."""

    mode: PermissionMode | None
    guarded: bool
    # The chat's folders: its own and its extra folders.
    folders: tuple[Path, ...]
    # Edits outside it are rejected in every mode (D072).
    write_root: Path | None = None
    nest: NestTools = field(default_factory=dict[str, frozenset[str]])
    # Worktree removals are rejected, guarded or not (Autopilot).
    worktrees: bool = False
    # A subagent's git writes are rejected where the engine marks its calls (Copilot).
    subagents: bool = False


class AcpPermissions:
    def __init__(
        self, handler: ApprovalHandler, rules: Callable[[], AcpRules], stream: AcpStream
    ) -> None:
        self._handler = handler
        self._rules = rules
        self._stream = stream
        self._always: set[tuple[str, str]] = set()
        self._asking: set[asyncio.Task[PermissionDecision]] = set()

    async def handle(self, params: JsonObject) -> JsonValue:
        """The answer to a `session/request_permission`."""
        options = [obj(option) for option in items(params.get("options"))]
        call = await self._stream.asked(obj(params.get("toolCall")))
        return answer(options, await self.verdict(call))

    def cancel_pending(self) -> None:
        for task in list(self._asking):
            task.cancel()

    async def verdict(self, call: ToolCall) -> Verdict:
        rules = self._rules()
        name, tool_input = tool_use(call, rules.nest)
        own = name.startswith("mcp__") and name.split("__")[1] in rules.nest
        pushes = rules.guarded or (rules.subagents and call.subagent)
        writes = git_write(call, name, pushes=pushes, worktrees=rules.worktrees)
        if writes or (pushes and not own and _blind_runner(call)):
            call.refused = DENY_REASON if pushes else WORKTREE_DENY_REASON
            return "reject"
        changed = paths(call)
        root = rules.write_root
        if call.kind in EDIT_KINDS and root is not None and not within(changed, (root,)):
            call.refused = OUTSIDE_ROOT.format(root=root)
            return "reject"
        if own:
            return "allow"
        if rules.mode in ("bypassPermissions", "auto"):
            return "allow"
        if call.kind in LOOK_KINDS and within(changed, rules.folders):
            return "allow"
        if (
            call.kind in EDIT_KINDS
            and rules.mode == "acceptEdits"
            and within(changed, rules.folders)
        ):
            return "allow"
        key = _always_key(call, name)
        if key in self._always:
            return "allow"
        decision = await self._ask(
            PermissionRequest(
                tool_name=name,
                tool_input=tool_input,
                title=call.title or None,
                always_rule=_always_rule(call, name),
            )
        )
        if decision is None:
            return "cancelled"
        if decision.behavior != "allow":
            return "reject"
        if decision.always:
            self._always.add(key)
        return "allow"

    async def _ask(self, request: PermissionRequest) -> PermissionDecision | None:
        """The user's decision; None when a Stop cancelled the question."""
        task = asyncio.create_task(self._handler.decide(request))
        self._asking.add(task)
        try:
            return await task
        except asyncio.CancelledError:
            current = asyncio.current_task()
            if current is not None and current.cancelling():
                raise
            return None
        finally:
            self._asking.discard(task)


def git_write(call: ToolCall, name: str, *, pushes: bool, worktrees: bool) -> bool:
    """Whether the call pushes, writes a pull request or removes a worktree, as far as the
    run blocks those: its command, else its title (where Gemini puts a command), and an MCP
    tool's name and input.
    """
    commands = [command_text(call)] if shell_call(call) else []
    if call.kind not in READ_KINDS | EDIT_KINDS:
        commands.append(call.title)
    if any(
        is_git_write(command, pushes=pushes, worktrees=worktrees) for command in commands if command
    ):
        return True
    tool = name if name.startswith("mcp__") or not unknown_kind(call) else _mcp_name(call)
    mcp = mcp_call(call)
    tool_input = call.raw_input if mcp is None else mcp.input
    return tool_writes(tool, tool_input, pushes=pushes, worktrees=worktrees)


def _blind_runner(call: ToolCall) -> bool:
    """An MCP tool asked about without its input whose name says it runs commands."""
    mcp = mcp_call(call)
    if not unknown_kind(call) or (call.raw_input if mcp is None else mcp.input):
        return False
    letters = "".join(c for c in title_name(call.title).lower() if c.isalpha())
    return bool(_RUNS_COMMANDS.search(letters))


def within(found: list[str], folders: tuple[Path, ...]) -> bool:
    """Whether there are paths and each is absolute and inside one of `folders`."""
    if not found:
        return False
    roots = [folder.resolve() for folder in folders]
    for path in found:
        candidate = Path(path)
        if not candidate.is_absolute():
            return False
        resolved = candidate.resolve()
        if not any(resolved == root or root in resolved.parents for root in roots):
            return False
    return True


def answer(options: list[JsonObject], verdict: Verdict) -> JsonValue:
    """The option that carries the verdict once; cancelled when the engine offers none
    (Nest never picks an option that allows always).
    """
    if verdict == "cancelled":
        return _CANCELLED
    chosen = _option(options, verdict == "allow")
    if chosen is None and verdict == "allow":
        logger.warning("the engine offered no option that allows once; the call is rejected")
        chosen = _option(options, allow=False)
    if chosen is None:
        return _CANCELLED
    return {"outcome": {"outcome": "selected", "optionId": chosen}}


def _option(options: list[JsonObject], allow: bool) -> str | None:
    kind = "allow_once" if allow else "reject_once"
    known = _ALLOW_ONCE if allow else _REJECT_ONCE
    for option in options:
        if option.get("kind") == kind and (option_id := text(option.get("optionId"))):
            return option_id
    for option in options:
        option_id = text(option.get("optionId"))
        if option_id in known:
            return option_id
    return None


def _mcp_name(call: ToolCall) -> str:
    """An MCP tool's name as the git guard reads it; the engine does not name the server."""
    return f"mcp__engine__{title_name(call.title)}"


def _always_key(call: ToolCall, name: str) -> tuple[str, str]:
    if shell_call(call):
        return ("command", command_text(call))
    if call.kind in EDIT_KINDS:
        return ("kind", call.kind)
    return ("tool", name)


def _always_rule(call: ToolCall, name: str) -> str:
    """What "Always allow" allows for the rest of the run, in Claude Code's words."""
    if shell_call(call):
        return f"Bash({command_text(call)})"
    return name
