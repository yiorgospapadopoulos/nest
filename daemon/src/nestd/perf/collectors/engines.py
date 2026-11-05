"""Engines (C13, live): the same tiny task on each signed-in engine, outside any chat (no
chat row is made), on its cheapest model; how soon it answered, how long it took and
what it cost in tokens. Local models are left out."""

import asyncio
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from nestd.config.models import PermissionMode
from nestd.perf.collectors.common import engine_name
from nestd.perf.models import Collected, Measured
from nestd.providers.base import (
    AgentProvider,
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
    RunAccount,
    SessionSpec,
    TextBlock,
    TokenUsage,
    UsageInfo,
    UserInput,
)

TASK = "Reply with the word ok"
TASK_SECONDS = 120.0
# Words that name an engine's small, cheap models, cheapest first.
_CHEAP = ("haiku", "nano", "mini", "flash", "lite", "small")


@dataclass(frozen=True)
class Target:
    """A signed-in engine to try, with what its run needs."""

    provider: AgentProvider
    # Its cheapest model (see `cheapest`); None leaves the engine's default.
    model: Callable[[], Awaitable[str | None]]
    account: Callable[[], Awaitable[RunAccount | None]]


@dataclass(frozen=True)
class TinyTurn:
    model: str | None
    first_ms: float | None
    total_ms: float
    tokens: int
    error: str | None


def cheapest(models: Sequence[ModelOption]) -> str | None:
    """The first model named like a small one; None leaves the engine's default."""
    for word in _CHEAP:
        for model in models:
            if word in f"{model.value} {model.display_name}".lower():
                return model.value
    return None


class Engines:
    def __init__(self, targets: Callable[[], Awaitable[list[Target]]], cwd: Path) -> None:
        """`targets` are the engines signed in now; `cwd` is an empty scratch folder."""
        self._targets = targets
        self._cwd = cwd

    async def __call__(self) -> Collected:
        metrics: list[Measured] = []
        failed: list[str] = []
        for target in await self._targets():
            name = engine_name(target.provider.name)
            turn = await tiny_turn(target, self._cwd)
            key = target.provider.name
            if turn.error is not None:
                failed.append(f"{name}: {turn.error}")
            sub = turn.model or "default model"
            metrics += [
                Measured(
                    id=f"{key}_first",
                    label=f"{name}, first reply",
                    unit="ms",
                    better="lower",
                    value=turn.first_ms,
                    sub=sub,
                ),
                Measured(
                    id=f"{key}_total",
                    label=f"{name}, whole task",
                    unit="ms",
                    better="lower",
                    value=None if turn.error else turn.total_ms,
                ),
                Measured(
                    id=f"{key}_tokens",
                    label=f"{name}, tokens",
                    unit="tokens",
                    better="lower",
                    value=None if turn.error else turn.tokens,
                ),
            ]
        note = "No engine is signed in." if not metrics else "; ".join(failed) or None
        return Collected(metrics=metrics, note=note)


async def tiny_turn(target: Target, cwd: Path) -> TinyTurn:
    """One turn of TASK on a run of its own that is closed after it."""
    await asyncio.to_thread(cwd.mkdir, parents=True, exist_ok=True)
    model = await target.model()
    spec = SessionSpec(
        cwd=cwd,
        permission_mode="default",
        model=model,
        guard_git=True,
        account=await target.account(),
        keep_history=False,
    )
    sink = _Sink()
    started = time.perf_counter()
    try:
        async with asyncio.timeout(TASK_SECONDS):
            run = await target.provider.open(spec, NoTools(), sink)
            try:
                sent = time.perf_counter()
                await run.send(UserInput(text=TASK))
                info = await sink.done
            finally:
                await run.close()
    except TimeoutError:
        return TinyTurn(model, None, 0.0, 0, "timed out")
    except Exception as error:  # one engine failing must not stop the rest
        return TinyTurn(model, None, 0.0, 0, type(error).__name__)
    first = None if sink.first_reply is None else (sink.first_reply - sent) * 1000
    total = (time.perf_counter() - started) * 1000
    tokens = _total(info.tokens)
    return TinyTurn(model, first, total, tokens, "failed" if info.is_error else None)


def _total(tokens: TokenUsage) -> int:
    return (
        tokens.input_tokens
        + tokens.output_tokens
        + tokens.cache_creation_input_tokens
        + tokens.cache_read_input_tokens
    )


class NoTools:
    """A one-off turn that needs no tools, questions or plans: each is refused."""

    async def decide(self, request: PermissionRequest) -> PermissionDecision:
        return PermissionDecision("deny", "Not needed for this check.")

    async def ask(self, request: QuestionRequest) -> QuestionAnswer:
        return QuestionAnswer(None)

    async def review_plan(self, request: PlanRequest) -> PlanDecision:
        return PlanDecision(approved=False)


class _Sink:
    """Hears when the first text came and how the turn ended; ignores everything else."""

    def __init__(self) -> None:
        self.first_reply: float | None = None
        self.done: asyncio.Future[ResultInfo] = asyncio.get_running_loop().create_future()

    def _replied(self) -> None:
        if self.first_reply is None:
            self.first_reply = time.perf_counter()

    async def message(self, blocks: list[MessageBlock], parent_tool_use_id: str | None) -> None:
        if parent_tool_use_id is None and any(isinstance(b, TextBlock) for b in blocks):
            self._replied()

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

    async def folder_changed(self, folder: Path, *, removed: bool) -> None: ...
