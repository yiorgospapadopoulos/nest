"""Engines (C13, live): the same tiny task on each signed-in engine, outside any chat (no
chat row is made), on its cheapest model; how soon it answered, how long it took and
what it cost in tokens. Local models are left out."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from nestd.perf.collectors.common import engine_name
from nestd.perf.models import Collected, Measured
from nestd.providers.base import AgentProvider, RunAccount, SessionSpec, TokenUsage, UserInput
from nestd.providers.one_off import NoTools, ReplySink

TASK = "Reply with the word ok"
TASK_SECONDS = 120.0


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
    sink = ReplySink()
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
