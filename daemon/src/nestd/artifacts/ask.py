"""An artifact page asks Claude (B88 stage 4, D118): one small Agent SDK call on the user's
own Claude Code login, modelled on the usage probe (D031): no tools, settings, MCP servers
or thinking, one turn, no transcript, in an empty folder. Each artifact has a daily budget,
one ask at a time, and the daemon runs a few at most; every open reader hears when one
starts and finishes.
"""

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from contextlib import suppress
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path

from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, ResultMessage, TextBlock
from pydantic import BaseModel, JsonValue

from nestd.clock import Clock
from nestd.config.models import ArtifactSettings
from nestd.errors import ConflictError, NestError
from nestd.events import types
from nestd.events.bus import EventBus
from nestd.providers.base import RunAccount, TokenUsage
from nestd.providers.claude_messages import token_usage
from nestd.storage.db import Database
from nestd.usage.probe import ProbeClientFactory
from nestd.usage.store import UsageStore

ASK_PREAMBLE = (
    "You answer a request from an interactive page the user opened in Nest. Reply with plain"
    " text only, no tools, briefly."
)
PROMPT_MAX = 8000
SYSTEM_MAX = 4000
ASK_TIMEOUT = timedelta(seconds=60)
# Asks running daemon-wide, and how long another waits for one of them to finish.
ASKS_AT_ONCE = 2
ASK_WAIT = timedelta(seconds=30)


class AskDisabledError(NestError):
    status_code = 403


class AskBudgetError(NestError):
    status_code = 429

    def __init__(self, message: str, resets_at: datetime) -> None:
        super().__init__(message)
        self.resets_at = resets_at

    def payload(self) -> dict[str, JsonValue]:
        return {"detail": str(self), "resets_at": self.resets_at.isoformat()}


class AskBusyError(ConflictError):
    pass


class AskFailedError(NestError):
    """Claude gave no answer; the message never quotes what the engine printed."""

    status_code = 502


class AskAnswer(BaseModel):
    text: str
    # Asks this artifact has left today, of `limit` a day.
    remaining: int
    limit: int


class AskStatus(BaseModel):
    """An artifact's asks today, by the local calendar."""

    used: int
    limit: int
    remaining: int
    # The next local midnight, when `used` starts again from 0.
    resets_at: datetime
    # Whether asking is turned on in settings.
    enabled: bool


def ask_options(
    cwd: Path,
    settings: ArtifactSettings,
    system: str | None,
    account: Mapping[str, str] | None = None,
) -> ClaudeAgentOptions:
    """`account` points Claude Code at the active account's profile (B98)."""
    prompt = ASK_PREAMBLE if not system else f"{ASK_PREAMBLE}\n\n{system}"
    return ClaudeAgentOptions(
        cwd=cwd,
        model=settings.ask_model,
        system_prompt=prompt,
        tools=[],
        # None of the user's settings: no CLAUDE.md, hooks, plugins or MCP servers load.
        setting_sources=[],
        strict_mcp_config=True,
        thinking={"type": "disabled"},
        max_turns=1,
        # No transcript in Claude Code's projects folder for every ask.
        extra_args={"no-session-persistence": None},
        env={
            "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(settings.ask_max_output_tokens),
            **(account or {}),
        },
    )


class PageAsks:
    def __init__(
        self,
        *,
        db: Database,
        bus: EventBus,
        clock: Clock,
        usage: UsageStore,
        factory: ProbeClientFactory,
        cwd: Path,
        settings: Callable[[], ArtifactSettings],
        zone: tzinfo | None = None,
        timeout: timedelta = ASK_TIMEOUT,
        wait: timedelta = ASK_WAIT,
        account: Callable[[], Awaitable[RunAccount]] | None = None,
    ) -> None:
        """`zone` decides the local day a budget counts; None is the system's zone.
        `account` is the Claude account asks run on (B98; None: Claude Code's own).
        """
        self._account = account
        self._db = db
        self._bus = bus
        self._clock = clock
        self._usage = usage
        self._factory = factory
        self._cwd = cwd
        self._settings = settings
        self._zone = zone
        self._timeout = timeout
        self._wait = wait
        self._slots = asyncio.Semaphore(ASKS_AT_ONCE)
        self._running: set[str] = set()

    async def status(self, artifact_id: str) -> AskStatus:
        settings = self._settings()
        start, end = self._today()
        row = await self._db.fetch_one(
            "SELECT COUNT(*) AS n FROM artifact_asks WHERE artifact_id = ? AND at >= ? AND at < ?",
            (artifact_id, _utc(start), _utc(end)),
        )
        assert row is not None  # noqa: S101 (COUNT always returns a row)
        used, limit = row["n"], settings.ask_daily_limit
        return AskStatus(
            used=used,
            limit=limit,
            remaining=max(limit - used, 0),
            resets_at=end,
            enabled=settings.ask,
        )

    async def ask(self, artifact_id: str, prompt: str, system: str | None) -> AskAnswer:
        """For an existing artifact; raises the reason a page cannot ask now."""
        settings = self._settings()
        if not settings.ask:
            msg = "Asking Claude from pages is turned off in Nest's settings"
            raise AskDisabledError(msg)
        if artifact_id in self._running:
            msg = "This page is already asking Claude; wait for the answer"
            raise AskBusyError(msg)
        self._running.add(artifact_id)
        try:
            today = await self.status(artifact_id)
            if not today.remaining:
                msg = (
                    f"This page has used its {today.limit} asks for today; they reset at"
                    f" {today.resets_at.isoformat()}"
                )
                raise AskBudgetError(msg, today.resets_at)
            await self._slot()
            try:
                return await self._run(artifact_id, prompt, system, settings, today)
            finally:
                self._slots.release()
        finally:
            self._running.discard(artifact_id)

    async def _slot(self) -> None:
        try:
            async with asyncio.timeout(self._wait.total_seconds()):
                await self._slots.acquire()
        except TimeoutError as error:
            msg = "Claude is busy with other pages' asks; try again shortly"
            raise AskBusyError(msg) from error

    async def _run(
        self,
        artifact_id: str,
        prompt: str,
        system: str | None,
        settings: ArtifactSettings,
        today: AskStatus,
    ) -> AskAnswer:
        remaining, limit = today.remaining - 1, today.limit
        await self._announce(artifact_id, "started", remaining, limit)
        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                env = None if self._account is None else (await self._account()).env
                options = ask_options(self._cwd, settings, system, env)
                text, tokens = await self._call(options, prompt)
        except Exception as error:
            await self._record(artifact_id, None)
            await self._announce(artifact_id, "finished", remaining, limit)
            raise AskFailedError(f"Claude did not answer ({_reason(error)})") from error
        await self._record(artifact_id, tokens)
        await self._usage.record_ask(tokens)
        await self._announce(artifact_id, "finished", remaining, limit)
        return AskAnswer(text=text, remaining=remaining, limit=limit)

    async def _call(self, options: ClaudeAgentOptions, prompt: str) -> tuple[str, TokenUsage]:
        client = self._factory(options)
        try:
            await client.connect()
            await client.query(prompt)
            parts: list[str] = []
            async for message in client.receive_messages():
                if isinstance(message, AssistantMessage):
                    parts.extend(b.text for b in message.content if isinstance(b, TextBlock))
                elif isinstance(message, ResultMessage):
                    if message.is_error:
                        msg = "the engine reported an error"
                        raise AskFailedError(msg)
                    text = "".join(parts).strip() or (message.result or "").strip()
                    return text, token_usage(message.usage or {})
            msg = "the engine ended before the reply"
            raise AskFailedError(msg)
        finally:
            with suppress(Exception):
                await client.disconnect()

    async def _record(self, artifact_id: str, tokens: TokenUsage | None) -> None:
        await self._db.execute(
            "INSERT INTO artifact_asks (artifact_id, at, input_tokens, output_tokens, ok)"
            " VALUES (?, ?, ?, ?, ?)",
            (
                artifact_id,
                _utc(self._clock.now()),
                None if tokens is None else tokens.input_tokens,
                None if tokens is None else tokens.output_tokens,
                int(tokens is not None),
            ),
        )

    async def _announce(self, artifact_id: str, state: str, remaining: int, limit: int) -> None:
        await self._bus.publish_ephemeral(
            types.ARTIFACT_ASK,
            {"artifact_id": artifact_id, "state": state, "remaining": remaining, "limit": limit},
        )

    def _today(self) -> tuple[datetime, datetime]:
        """The start of today and of tomorrow, by the local calendar."""
        day = self._clock.now().astimezone(self._zone).date()
        return self._midnight(day), self._midnight(day + timedelta(days=1))

    def _midnight(self, day: date) -> datetime:
        wall = datetime.combine(day, time())
        # A naive time's astimezone() reads it in the system's zone, clock changes included.
        return wall.astimezone() if self._zone is None else wall.replace(tzinfo=self._zone)


def _utc(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat()


def _reason(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timed out"
    if isinstance(error, AskFailedError):
        return str(error)
    return type(error).__name__
