"""A scriptable agent provider. Each run has one reader that plays turns, like the CLI:
turns answering user messages and turns the agent starts on its own.
"""

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from pathlib import Path

from nestd.config.models import PermissionMode
from nestd.providers.base import (
    AgentTask,
    ApprovalHandler,
    CommandCatalog,
    ContextUsage,
    EngineDetails,
    McpServer,
    MessageBlock,
    PermissionDecision,
    PermissionRequest,
    PlanDecision,
    PlanRequest,
    ProviderEventSink,
    QuestionAnswer,
    QuestionRequest,
    ResultInfo,
    RewindResult,
    SessionSpec,
    TextBlock,
    TokenUsage,
    UsageInfo,
    UserInput,
)
from tests.git_support import commit_file

type Turn = Callable[["FakeRun"], Awaitable[None]]


class AgentCrashedError(Exception):
    """A scripted turn raising this ends the run as if the CLI process died."""


class FakeRun:
    def __init__(
        self,
        provider: "FakeProvider",
        spec: SessionSpec,
        handler: ApprovalHandler,
        sink: ProviderEventSink,
    ) -> None:
        self.provider = provider
        self.spec = spec
        self.handler = handler
        self.sink = sink
        self.inputs: list[UserInput] = []
        self.calls: list[tuple[str, object]] = []
        self.status_calls = 0
        self.decisions: list[PermissionDecision] = []
        self.answers: list[QuestionAnswer] = []
        self.plans: list[PlanDecision] = []
        self.interrupted = asyncio.Event()
        self.closed = False
        self._turns: asyncio.Queue[Turn] = asyncio.Queue()
        self._reader = asyncio.create_task(self._read())

    async def send(self, user_input: UserInput) -> None:
        self.inputs.append(user_input)
        self._turns.put_nowait(self.provider.turns.popleft())
        if self.provider.send_gate is not None:
            # The turn runs before send returns, as a fast reply could in the real engine.
            await self.provider.send_gate.wait()

    def emit(self, turn: Turn) -> None:
        """A turn the agent starts without a user message."""
        self._turns.put_nowait(turn)

    async def interrupt(self) -> None:
        self.calls.append(("interrupt", None))
        self.interrupted.set()

    async def set_model(self, model: str | None) -> None:
        self.calls.append(("set_model", model))

    async def connector_statuses(self) -> list[McpServer]:
        self.status_calls += 1
        if self.provider.status_gate is not None:
            await self.provider.status_gate.wait()
        if self.provider.status_error is not None:
            raise self.provider.status_error
        return self.provider.statuses

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        self.calls.append(("set_permission_mode", mode))

    async def context_usage(self) -> ContextUsage | None:
        if self.provider.context_gate is not None:
            await self.provider.context_gate.wait()
        if self.provider.context_error is not None:
            raise self.provider.context_error
        return self.provider.context

    async def rewind_files(self, checkpoint_id: str, dry_run: bool) -> RewindResult:
        self.calls.append(("rewind_files", (checkpoint_id, dry_run)))
        return self.provider.rewind

    async def close(self) -> None:
        self._reader.cancel()
        await asyncio.gather(self._reader, return_exceptions=True)
        if self.provider.exit_hook:
            # Like a SessionEnd hook writing into the working directory as the CLI exits.
            (self.spec.cwd / ".remember").mkdir(exist_ok=True)
        self.closed = True
        if self.provider.close_error is not None:
            raise self.provider.close_error

    async def _read(self) -> None:
        while True:
            turn = await self._turns.get()
            try:
                await turn(self)
            except AgentCrashedError as error:
                self.closed = True
                await self.sink.stopped(str(error))
                return


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.turns: deque[Turn] = deque()
        self.runs: list[FakeRun] = []
        self.open_error: Exception | None = None
        self.close_error: Exception | None = None
        # What the run reports as the live status of its MCP servers after each turn.
        self.statuses: list[McpServer] = []
        self.status_error: Exception | None = None
        # When set, the status and context calls wait for it, like a control request the
        # engine has not answered yet.
        self.status_gate: asyncio.Event | None = None
        self.context_gate: asyncio.Event | None = None
        self.exit_hook = False
        # When set, open() waits for it, so a test can act while a run is opening.
        self.open_gate: asyncio.Event | None = None
        # When set, send() waits for it after the turn is queued.
        self.send_gate: asyncio.Event | None = None
        # What the run reports as its context usage after each turn.
        self.context: ContextUsage | None = None
        self.context_error: Exception | None = None
        # What restoring files to a checkpoint previews or does.
        self.rewind = RewindResult(can_rewind=True, files_changed=["a.py"], insertions=2)

    async def open(
        self, spec: SessionSpec, handler: ApprovalHandler, sink: ProviderEventSink
    ) -> FakeRun:
        if self.open_gate is not None:
            await self.open_gate.wait()
        if self.open_error is not None:
            raise self.open_error
        run = FakeRun(self, spec, handler, sink)
        self.runs.append(run)
        return run

    def script(self, *turns: Turn) -> None:
        self.turns.extend(turns)


RESULT = ResultInfo(
    is_error=False, subtype="success", duration_ms=10, num_turns=1, cost_usd=0.01, errors=[]
)


def reply(text: str, provider_session_id: str = "sdk-1", tokens: TokenUsage | None = None) -> Turn:
    async def turn(run: FakeRun) -> None:
        await run.sink.provider_session_id(provider_session_id)
        await run.sink.text_delta(text)
        await run.sink.message([TextBlock(text=text)], None)
        await run.sink.result(RESULT.model_copy(update={"tokens": tokens or TokenUsage()}))

    return turn


def engine_error(*errors: str, subtype: str = "error_during_execution") -> Turn:
    """A turn the engine ends with an error result, such as a usage limit or an API error."""

    async def turn(run: FakeRun) -> None:
        await run.sink.provider_session_id("sdk-1")
        await run.sink.result(
            RESULT.model_copy(update={"is_error": True, "subtype": subtype, "errors": [*errors]})
        )

    return turn


def switched(mode: PermissionMode, then: Turn) -> Turn:
    """The engine changes its permission mode itself and says so."""

    async def turn(run: FakeRun) -> None:
        await run.sink.permission_mode(mode)
        await then(run)

    return turn


def loaded(servers: list[McpServer], then: Turn) -> Turn:
    """The engine reports the MCP servers it loaded, as the CLI does when it starts."""

    async def turn(run: FakeRun) -> None:
        await run.sink.connectors(servers)
        await then(run)

    return turn


def limits(info: UsageInfo, then: Turn) -> Turn:
    async def turn(run: FakeRun) -> None:
        await run.sink.usage(info)
        await then(run)

    return turn


def ask(tool: str, then: Turn) -> Turn:
    async def turn(run: FakeRun) -> None:
        run.decisions.append(await run.handler.decide(PermissionRequest(tool, {"x": 1})))
        await then(run)

    return turn


def ask_together(*tools: str, then: Turn) -> Turn:
    """Parallel tool calls: several permission prompts open at once."""

    async def turn(run: FakeRun) -> None:
        requests = (run.handler.decide(PermissionRequest(tool, {})) for tool in tools)
        run.decisions.extend(await asyncio.gather(*requests))
        await then(run)

    return turn


def question(request: QuestionRequest, then: Turn) -> Turn:
    async def turn(run: FakeRun) -> None:
        run.answers.append(await run.handler.ask(request))
        await then(run)

    return turn


def messages(*items: tuple[list[MessageBlock], str | None], then: Turn) -> Turn:
    """The agent's transcript: blocks with their parent tool use id (None: main agent)."""

    async def turn(run: FakeRun) -> None:
        for blocks, parent in items:
            await run.sink.message(blocks, parent)
        await then(run)

    return turn


def edit(files: dict[str, str], then: Turn) -> Turn:
    """Writes files in the session's working directory, as an agent editing code would."""

    async def turn(run: FakeRun) -> None:
        for name, content in files.items():
            path = Path(run.spec.cwd) / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        await then(run)

    return turn


def until_interrupted() -> Turn:
    async def turn(run: FakeRun) -> None:
        await run.sink.text_delta("working")
        await run.interrupted.wait()
        await run.sink.result(RESULT.model_copy(update={"subtype": "interrupted"}))

    return turn


def hang() -> Turn:
    async def turn(run: FakeRun) -> None:
        await run.sink.text_delta("working")
        await asyncio.Event().wait()

    return turn


def stopped_then_result() -> Turn:
    """The process ends, yet a turn result still arrives from what it printed last."""

    async def turn(run: FakeRun) -> None:
        await run.sink.stopped("the agent process ended")
        await run.sink.result(RESULT)

    return turn


def background(running: int, then: Turn | None = None) -> Turn:
    """Reports the agent's running background tasks, then optionally continues."""

    async def turn(run: FakeRun) -> None:
        await run.sink.background_tasks(running)
        if then is not None:
            await then(run)

    return turn


def tasks(*updates: AgentTask, then: Turn | None = None) -> Turn:
    """Reports task lifecycle updates, then optionally continues."""

    async def turn(run: FakeRun) -> None:
        for update in updates:
            await run.sink.task(update)
        if then is not None:
            await then(run)

    return turn


def crash(message: str) -> Turn:
    async def turn(_run: FakeRun) -> None:
        raise AgentCrashedError(message)

    return turn


def commit(then: Turn) -> Turn:
    """Commits in the session's working directory, as Claude does when the user asks (B58)."""

    async def turn(run: FakeRun) -> None:
        commit_file(Path(run.spec.cwd), "sneaky.txt")
        await then(run)

    return turn


def plan(text: str, then: Turn) -> Turn:
    """The agent presents a plan in plan mode and waits for the user's decision."""

    async def turn(run: FakeRun) -> None:
        run.plans.append(await run.handler.review_plan(PlanRequest(text, "toolu_plan")))
        await then(run)

    return turn


def catalog(reported: CommandCatalog, then: Turn) -> Turn:
    """The engine reports its slash commands and agents."""

    async def turn(run: FakeRun) -> None:
        await run.sink.commands(reported)
        await then(run)

    return turn


def engine(details: EngineDetails, then: Turn) -> Turn:
    """The engine reports its models and account, as it does when a run opens."""

    async def turn(run: FakeRun) -> None:
        await run.sink.engine_details(details)
        await then(run)

    return turn


def echoed(checkpoint_id: str, then: Turn) -> Turn:
    """The engine echoes the user message it was sent, with the id of its file checkpoint."""

    async def turn(run: FakeRun) -> None:
        await run.sink.checkpoint(checkpoint_id)
        await then(run)

    return turn
