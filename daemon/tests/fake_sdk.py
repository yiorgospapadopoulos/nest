"""A stand-in for ClaudeSDKClient whose message stream the test feeds."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from typing import Any, cast

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ContextUsageResponse,
    McpStatusResponse,
    Message,
    PermissionMode,
)

# None ends the stream as if the process exited; an exception is raised from the stream.
type StreamItem = Message | Exception | None


class FakeSdkClient:
    def __init__(self, options: ClaudeAgentOptions) -> None:
        self.options = options
        self.stream: asyncio.Queue[StreamItem] = asyncio.Queue()
        self.connected = False
        self.disconnects = 0
        self.prompts: list[dict[str, Any]] = []
        self.calls: list[tuple[str, object]] = []
        self.mcp_status: McpStatusResponse = {"mcpServers": []}
        # The initialize response; None as while connect() is still in progress.
        self.server_info: dict[str, Any] | None = None
        # What get_context_usage returns; tests also give malformed responses.
        self.context: dict[str, Any] = {}

    def push(self, *items: StreamItem) -> None:
        for item in items:
            self.stream.put_nowait(item)

    async def connect(self) -> None:
        self.connected = True

    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = "default"
    ) -> None:
        assert not isinstance(prompt, str)
        async for message in prompt:
            self.prompts.append(message)

    async def receive_messages(self) -> AsyncIterator[Message]:
        while True:
            item = await self.stream.get()
            if item is None:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    async def interrupt(self) -> None:
        self.calls.append(("interrupt", None))

    async def set_model(self, model: str | None = None) -> None:
        self.calls.append(("set_model", model))

    async def set_permission_mode(self, mode: PermissionMode) -> None:
        self.calls.append(("set_permission_mode", mode))

    async def get_mcp_status(self) -> McpStatusResponse:
        return self.mcp_status

    async def get_context_usage(self) -> ContextUsageResponse:
        return cast("ContextUsageResponse", self.context)

    async def get_server_info(self) -> dict[str, Any] | None:
        return self.server_info

    async def disconnect(self) -> None:
        self.disconnects += 1
