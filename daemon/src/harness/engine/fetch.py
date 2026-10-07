"""Reads the engine's model list and account from a short-lived Claude Code process (D038).

Connecting runs Claude Code's initialize handshake only: no prompt, no model call, no tokens.
"""

import asyncio
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import timedelta
from pathlib import Path
from typing import Any, Protocol

from claude_agent_sdk import ClaudeAgentOptions

from harness.providers.base import EngineDetails
from harness.providers.claude_engine import engine_details

FETCH_TIMEOUT = timedelta(seconds=60)


class InfoClient(Protocol):
    """The part of ClaudeSDKClient the fetch uses; tests substitute a fake."""

    async def connect(self) -> None: ...

    async def get_server_info(self) -> dict[str, Any] | None: ...

    async def disconnect(self) -> None: ...


type InfoClientFactory = Callable[[ClaudeAgentOptions], InfoClient]


class FetchError(Exception):
    """The engine reported nothing usable; the message never quotes CLI output."""


def info_options(cwd: Path) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        cwd=cwd,
        # The user's own settings, so the list matches their Claude Code; no project files.
        setting_sources=["user"],
        tools=[],
        strict_mcp_config=True,
        # No transcript in Claude Code's projects folder.
        extra_args={"no-session-persistence": None},
    )


async def fetch_details(
    factory: InfoClientFactory, time_limit: timedelta = FETCH_TIMEOUT
) -> EngineDetails:
    """Start Claude Code in an empty temporary folder, read its initialize response, stop it."""
    with tempfile.TemporaryDirectory(prefix="harness-engine-") as cwd:
        client = factory(info_options(Path(cwd)))
        try:
            async with asyncio.timeout(time_limit.total_seconds()):
                await client.connect()
                info = await client.get_server_info()
        except Exception as error:
            raise FetchError(_reason(error)) from error
        finally:
            with suppress(Exception):
                await client.disconnect()
    details = engine_details(info)
    if details is None:
        msg = "Claude Code reported no models or account"
        raise FetchError(msg)
    return details


def _reason(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "timed out"
    # Engine errors can quote what the CLI printed; only their kind is kept for the log.
    return type(error).__name__
