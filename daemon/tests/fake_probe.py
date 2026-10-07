"""A stand-in for the usage probe's ClaudeSDKClient: each prompt plays the next scripted reply."""

import asyncio
from collections.abc import AsyncIterable, AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    Message,
    RateLimitEvent,
    RateLimitInfo,
    ResultMessage,
    TextBlock,
)

# A reply is the messages after one prompt; an exception is raised from the stream instead.
type Reply = list[Message] | Exception


def rate_limit(five_hour: float, seven_day: float | None = None) -> RateLimitEvent:
    windows: dict[str, Any] = {"five_hour": {"utilization": five_hour, "resetsAt": 1791300600}}
    if seven_day is not None:
        windows["seven_day"] = {"utilization": seven_day, "resetsAt": 1791802800}
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(status="allowed", raw={"unifiedWindows": windows}),
        uuid="u",
        session_id="probe",
    )


def result(input_tokens: int = 450, output_tokens: int = 2) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=800,
        duration_api_ms=700,
        is_error=False,
        num_turns=1,
        session_id="probe",
        usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
    )


def answer(five_hour: float = 0.42, seven_day: float | None = 0.12) -> list[Message]:
    reply = AssistantMessage(content=[TextBlock("ok")], model="claude-haiku")
    return [rate_limit(five_hour, seven_day), reply, result()]


@dataclass
class FakeProbeClient:
    options: ClaudeAgentOptions
    replies: list[Reply]
    prompts: list[str] = field(default_factory=list[str])
    connected: bool = False
    disconnects: int = 0
    # Set to make connect fail, or to make a reply hang until the probe gives up.
    connect_error: Exception | None = None
    hang: bool = False
    disconnect_error: Exception | None = None

    async def connect(self) -> None:
        if self.connect_error is not None:
            raise self.connect_error
        self.connected = True

    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = ""
    ) -> None:
        assert isinstance(prompt, str)
        self.prompts.append(prompt)

    async def receive_messages(self) -> AsyncIterator[Message]:
        if self.hang:
            await asyncio.Event().wait()
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        for message in reply:
            yield message

    async def disconnect(self) -> None:
        self.disconnects += 1
        self.connected = False
        if self.disconnect_error is not None:
            raise self.disconnect_error


@dataclass
class FakeProbeFactory:
    """Creates a client per probe process; every client shares the scripted replies."""

    replies: list[Reply] = field(default_factory=list[Reply])
    clients: list[FakeProbeClient] = field(default_factory=list[FakeProbeClient])
    connect_error: Exception | None = None
    hang: bool = False

    def __call__(self, options: ClaudeAgentOptions) -> FakeProbeClient:
        client = FakeProbeClient(
            options, self.replies, connect_error=self.connect_error, hang=self.hang
        )
        self.clients.append(client)
        return client

    @property
    def prompts(self) -> int:
        return sum(len(client.prompts) for client in self.clients)
