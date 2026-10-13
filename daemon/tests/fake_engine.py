"""A stand-in for the short-lived ClaudeSDKClient that reads the engine's model list."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions

LEVELS = ["low", "medium", "high", "xhigh", "max"]


def server_info(
    *values: str, plan: str = "Claude Max", auto: tuple[str, ...] = ()
) -> dict[str, Any]:
    """An initialize response listing `values` (Haiku without effort levels); those in
    `auto` support Auto mode.
    """
    models: list[dict[str, Any]] = []
    for value in values:
        entry: dict[str, Any] = {
            "value": value,
            "displayName": value.capitalize(),
            "description": f"{value} model",
        }
        if value != "haiku":
            entry |= {"supportsEffort": True, "supportedEffortLevels": LEVELS}
        if value in auto:
            entry |= {"supportsAutoMode": True}
        models.append(entry)
    return {
        "models": models,
        "account": {
            "email": "person@example.com",
            "organization": "Acme",
            "subscriptionType": plan,
        },
        "commands": [],
    }


def _is_dir(path: str | Path | None) -> bool:
    return path is not None and Path(path).is_dir()


@dataclass
class FakeInfoClient:
    options: ClaudeAgentOptions
    info: dict[str, Any] | None
    connect_error: Exception | None = None
    hang: bool = False
    disconnect_error: Exception | None = None
    connected: bool = False
    disconnects: int = 0
    # The working directory existed while the client was connected.
    cwd_existed: bool = False

    async def connect(self) -> None:
        if self.hang:
            await asyncio.Event().wait()
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True
        self.cwd_existed = _is_dir(self.options.cwd)

    async def get_server_info(self) -> dict[str, Any] | None:
        return self.info

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.connected = False
        if self.disconnect_error is not None:
            raise self.disconnect_error


@dataclass
class FakeInfoFactory:
    """Each fetch creates a client answering with `info`; set errors to make it fail."""

    info: dict[str, Any] | None = field(default_factory=lambda: server_info("default", "haiku"))
    connect_error: Exception | None = None
    hang: bool = False
    disconnect_error: Exception | None = None
    clients: list[FakeInfoClient] = field(default_factory=list[FakeInfoClient])

    def __call__(self, options: ClaudeAgentOptions) -> FakeInfoClient:
        client = FakeInfoClient(
            options,
            self.info,
            connect_error=self.connect_error,
            hang=self.hang,
            disconnect_error=self.disconnect_error,
        )
        self.clients.append(client)
        return client
