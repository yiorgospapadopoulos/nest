"""The smallest Claude turn there is, sent only for the usage windows the engine reports (D031).

Claude reports the subscription's five-hour and seven-day windows only alongside a turn, so
numbers go stale while the user works elsewhere. One long-lived client answers a one-word
message on Haiku, without tools, settings, MCP servers or thinking: about 450 input tokens.
"""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import ClaudeAgentOptions, Message, RateLimitEvent, ResultMessage

from nestd.providers.base import RunAccount, TokenUsage, UsageInfo
from nestd.providers.claude_messages import token_usage, usage_info

PROBE_MODEL = "haiku"
PROBE_SYSTEM_PROMPT = "Reply with: ok"
PROBE_PROMPT = "ok"
PROBE_TIMEOUT = timedelta(seconds=60)
# Each exchange stays in the probe's conversation; a fresh client now and then keeps it tiny.
MAX_PROBES_PER_CLIENT = 20


class ProbeClient(Protocol):
    """The part of ClaudeSDKClient the probe uses; tests substitute a fake."""

    async def connect(self) -> None: ...

    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = ...
    ) -> None: ...

    def receive_messages(self) -> AsyncIterator[Message]: ...

    async def disconnect(self) -> None: ...


type ProbeClientFactory = Callable[[ClaudeAgentOptions], ProbeClient]


class ProbeError(Exception):
    """The probe got no answer; the message never contains credentials."""


@dataclass(frozen=True)
class ProbeOutcome:
    # None when the engine reported no usage windows with this turn.
    limits: UsageInfo | None
    tokens: TokenUsage


def probe_options(cwd: Path, env: Mapping[str, str] | None = None) -> ClaudeAgentOptions:
    """`env` points Claude Code at an added account's profile (B98)."""
    return ClaudeAgentOptions(
        cwd=cwd,
        env=dict(env or {}),
        model=PROBE_MODEL,
        system_prompt=PROBE_SYSTEM_PROMPT,
        tools=[],
        # None of the user's settings: no CLAUDE.md, hooks, plugins or MCP servers load.
        setting_sources=[],
        strict_mcp_config=True,
        thinking={"type": "disabled"},
        max_turns=1,
        # No transcript in Claude Code's projects folder for every probe.
        extra_args={"no-session-persistence": None},
    )


class UsageProbe:
    def __init__(
        self, factory: ProbeClientFactory, cwd: Path, timeout: timedelta = PROBE_TIMEOUT
    ) -> None:
        self._factory = factory
        self._cwd = cwd
        self._timeout = timeout
        self._client: ProbeClient | None = None
        # The account the open client runs on (B98).
        self._account: RunAccount | None = None
        self._probes = 0

    async def run(self, account: RunAccount | None = None) -> ProbeOutcome:
        """One exchange on the long-lived client, which opens on demand on `account`
        (None: Claude Code's own environment); a client on another account is closed first.

        Raises ProbeError on any failure, after closing the client so the next probe
        starts a new process.
        """
        if self._client is not None and self._account != account:
            await self.close()
        try:
            async with asyncio.timeout(self._timeout.total_seconds()):
                outcome = await self._exchange(account)
        except Exception as error:
            await self.close()
            raise ProbeError(_reason(error)) from error
        self._probes += 1
        if outcome.limits is None or self._probes >= MAX_PROBES_PER_CLIENT:
            await self.close()
        return outcome

    async def close(self) -> None:
        client, self._client = self._client, None
        self._probes = 0
        if client is not None:
            with suppress(Exception):
                await client.disconnect()

    async def _exchange(self, account: RunAccount | None) -> ProbeOutcome:
        if self._client is None:
            client = self._factory(
                probe_options(self._cwd, None if account is None else account.env)
            )
            self._client = client
            self._account = account
            await client.connect()
        await self._client.query(PROBE_PROMPT)
        limits: UsageInfo | None = None
        async for message in self._client.receive_messages():
            if isinstance(message, RateLimitEvent):
                limits = usage_info(message.rate_limit_info.raw) or limits
            elif isinstance(message, ResultMessage):
                return ProbeOutcome(limits, token_usage(message.usage or {}))
        msg = "the probe process ended before the reply"
        raise ProbeError(msg)


def _reason(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timed out"
    if isinstance(error, ProbeError):
        return str(error)
    # Engine errors can quote what the CLI printed; only their kind is kept for the log.
    return type(error).__name__
