import logging
from collections.abc import AsyncIterator

import httpx
import pytest

from harness.config.models import NtfySettings
from harness.notifications.messages import Notice
from harness.notifications.ntfy import NtfyChannel
from tests.push_support import FakeServers, json_body

URGENT = Notice(
    kind="question",
    title="Question · harness",
    body="Fix login: Which database?",
    url="/inbox",
    tag="session-s1",
    urgent=True,
)


@pytest.fixture
def servers() -> FakeServers:
    return FakeServers()


@pytest.fixture
async def channel(servers: FakeServers) -> AsyncIterator[NtfyChannel]:
    async with httpx.AsyncClient(transport=servers.transport()) as client:
        yield NtfyChannel(client)


async def test_publishes_json_with_title_priority_and_click_link(
    channel: NtfyChannel, servers: FakeServers
) -> None:
    settings = NtfySettings(
        enabled=True,
        server="https://ntfy.example.org/",
        topic="harness-k2v9x7q4",
        click_base_url="https://mac.tailnet.ts.net/",
    )

    assert await channel.send(URGENT, settings) is True

    [request] = servers.to("https://ntfy.example.org/")
    assert json_body(request) == {
        "topic": "harness-k2v9x7q4",
        "title": "Question · harness",
        "message": "Fix login: Which database?",
        "priority": 4,
        "tags": ["question"],
        "click": "https://mac.tailnet.ts.net/inbox",
    }


async def test_routine_notices_have_default_priority_and_no_link_without_a_base(
    channel: NtfyChannel, servers: FakeServers
) -> None:
    routine = Notice(kind="finished", title="t", body="b", url="/chat/s", tag="x", urgent=False)

    await channel.send(routine, NtfySettings(enabled=True, topic="harness-topic-k2v9x7"))

    body = json_body(servers.to("https://ntfy.sh/")[0])
    assert body["priority"] == 3
    assert "click" not in body


async def test_disabled_or_topicless_channels_send_nothing(
    channel: NtfyChannel, servers: FakeServers
) -> None:
    assert await channel.send(URGENT, NtfySettings(topic="harness-topic-k2v9x7")) is False
    assert await channel.send(URGENT, NtfySettings.model_construct(enabled=True)) is False
    assert servers.requests == []


async def test_failures_are_logged_without_the_topic(
    channel: NtfyChannel, servers: FakeServers, caplog: pytest.LogCaptureFixture
) -> None:
    servers.statuses["https://ntfy.sh/"] = 429
    settings = NtfySettings(enabled=True, topic="secret-topic-k2v9x7q4")

    with caplog.at_level(logging.WARNING):
        assert await channel.send(URGENT, settings) is False
        servers.broken.add("https://ntfy.sh/")
        assert await channel.send(URGENT, settings) is False

    assert "429" in caplog.text
    assert "ConnectError" in caplog.text
    assert "secret-topic-k2v9x7q4" not in caplog.text
