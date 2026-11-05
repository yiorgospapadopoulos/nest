"""What a single turn of Nest's own needs, outside any chat: the cheapest model, a handler
that refuses tools and a sink that keeps only the reply. Runs on the engine's own login.
"""

import asyncio
import time
from collections.abc import Sequence
from pathlib import Path

from nestd.config.models import PermissionMode
from nestd.providers.base import (
    AgentTask,
    CommandCatalog,
    EngineDetails,
    HookOutput,
    LimitHit,
    McpServer,
    MessageBlock,
    ModelOption,
    NoticeKind,
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    PlanStep,
    QuestionAnswer,
    QuestionRequest,
    ResultInfo,
    TextBlock,
    TokenUsage,
    UsageInfo,
)

# Words that name an engine's small, cheap models, cheapest first.
_CHEAP = ("haiku", "nano", "mini", "lite", "flash", "luna", "small")


def cheapest(models: Sequence[ModelOption]) -> str | None:
    """The first model named like a small one; None leaves the engine's default."""
    for word in _CHEAP:
        for model in models:
            if word in f"{model.value} {model.display_name}".lower():
                return model.value
    return None


class NoTools:
    """A one-off turn that needs no tools, questions or plans: each is refused."""

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision("deny", "Not needed for this check.")

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        return QuestionAnswer(None)

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        return PlanDecision(approved=False)


class ReplySink:
    """Keeps the reply, when it began and how the turn ended; ignores everything else."""

    def __init__(self) -> None:
        self.first_reply: float | None = None
        self.reply = ""
        self.done: asyncio.Future[ResultInfo] = asyncio.get_running_loop().create_future()

    def _replied(self) -> None:
        if self.first_reply is None:
            self.first_reply = time.perf_counter()

    async def message(self, blocks: list[MessageBlock], parent_tool_use_id: str | None) -> None:
        if parent_tool_use_id is not None:
            return
        for block in blocks:
            if isinstance(block, TextBlock):
                self._replied()
                self.reply += block.text

    async def text_delta(self, text: str) -> None:
        self._replied()

    async def result(self, info: ResultInfo) -> None:
        if not self.done.done():
            self.done.set_result(info)

    async def stopped(self, error: str) -> None:
        if not self.done.done():
            self.done.set_exception(RuntimeError(error))

    async def thinking(self, active: bool) -> None: ...

    async def thinking_delta(self, text: str, parent_tool_use_id: str | None) -> None: ...

    async def subagent_delta(self, text: str, parent_tool_use_id: str) -> None: ...

    async def hook(self, output: HookOutput) -> None: ...

    async def usage(self, info: UsageInfo) -> None: ...

    async def subagent_usage(self, message_id: str, tokens: TokenUsage) -> None: ...

    async def limit_hit(self, hit: LimitHit) -> None: ...

    async def provider_session_id(self, session_id: str) -> None: ...

    async def folder_changed(self, folder: Path, *, removed: bool) -> None: ...

    async def connectors(self, servers: list[McpServer]) -> None: ...

    async def commands(self, catalog: CommandCatalog) -> None: ...

    async def engine_details(self, details: EngineDetails) -> None: ...

    async def background_tasks(self, running: int) -> None: ...

    async def plan(self, steps: list[PlanStep], parent_tool_use_id: str | None) -> None: ...

    async def task(self, update: AgentTask) -> None: ...

    async def notice(self, kind: NoticeKind, text: str) -> None: ...

    async def permission_mode(self, mode: PermissionMode) -> None: ...

    async def checkpoint(self, checkpoint_id: str) -> None: ...

    async def message_taken(self, message_id: str, checkpoint_id: str) -> None: ...
