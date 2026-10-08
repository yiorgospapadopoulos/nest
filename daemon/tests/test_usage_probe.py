from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from harness.providers.base import TokenUsage, UsageInfo, UsageWindow
from harness.usage.probe import (
    MAX_PROBES_PER_CLIENT,
    PROBE_PROMPT,
    ProbeError,
    UsageProbe,
    probe_options,
)
from tests.fake_probe import FakeProbeFactory, answer, result


def test_the_probe_is_as_small_as_a_claude_turn_can_be(tmp_path: Path) -> None:
    options = probe_options(tmp_path)

    assert options.model == "haiku"
    assert options.tools == []
    # No user, project or local settings: no CLAUDE.md, hooks, plugins or MCP servers.
    assert options.setting_sources == []
    assert options.strict_mcp_config is True
    assert options.mcp_servers == {}
    assert options.system_prompt == "Reply with: ok"
    assert options.thinking == {"type": "disabled"}
    assert options.max_turns == 1
    assert options.extra_args == {"no-session-persistence": None}
    assert options.cwd == tmp_path


async def test_a_probe_reports_the_windows_and_its_tokens(tmp_path: Path) -> None:
    factory = FakeProbeFactory(replies=[answer(0.42, 0.12)])
    probe = UsageProbe(factory, tmp_path)

    outcome = await probe.run()

    assert outcome.limits == UsageInfo(
        five_hour=UsageWindow(utilization=0.42, resets_at=datetime.fromtimestamp(1791300600, UTC)),
        seven_day=UsageWindow(utilization=0.12, resets_at=datetime.fromtimestamp(1791802800, UTC)),
    )
    assert outcome.tokens == TokenUsage(input_tokens=450, output_tokens=2)
    assert factory.clients[0].prompts == [PROBE_PROMPT]
    assert factory.clients[0].options.cwd == tmp_path
    # Kept open for the next probe.
    assert factory.clients[0].disconnects == 0


async def test_one_client_serves_many_probes(tmp_path: Path) -> None:
    factory = FakeProbeFactory(replies=[answer(0.1), answer(0.2)])
    probe = UsageProbe(factory, tmp_path)

    await probe.run()
    second = await probe.run()

    assert len(factory.clients) == 1
    assert factory.clients[0].prompts == [PROBE_PROMPT, PROBE_PROMPT]
    assert second.limits is not None
    assert second.limits.five_hour is not None
    assert second.limits.five_hour.utilization == 0.2


async def test_the_client_is_replaced_after_many_probes(tmp_path: Path) -> None:
    """The probe conversation grows with each exchange; a fresh one keeps it tiny."""
    factory = FakeProbeFactory(replies=[answer() for _ in range(MAX_PROBES_PER_CLIENT + 1)])
    probe = UsageProbe(factory, tmp_path)

    for _ in range(MAX_PROBES_PER_CLIENT):
        await probe.run()

    assert factory.clients[0].disconnects == 1
    await probe.run()
    assert len(factory.clients) == 2


async def test_a_turn_without_windows_closes_the_client(tmp_path: Path) -> None:
    """The engine may only report windows that changed; a new process reports them again."""
    factory = FakeProbeFactory(replies=[[result()]])
    probe = UsageProbe(factory, tmp_path)

    outcome = await probe.run()

    assert outcome.limits is None
    assert outcome.tokens.input_tokens == 450
    assert factory.clients[0].disconnects == 1


@pytest.mark.parametrize(
    ("factory", "message"),
    [
        (FakeProbeFactory(connect_error=ConnectionError("not logged in")), "^ConnectionError$"),
        (FakeProbeFactory(replies=[RuntimeError("token sk-ant-1")]), "^RuntimeError$"),
        (FakeProbeFactory(replies=[[]]), "ended before the reply"),
    ],
)
async def test_a_failed_probe_raises_and_closes_the_client(
    tmp_path: Path, factory: FakeProbeFactory, message: str
) -> None:
    probe = UsageProbe(factory, tmp_path)

    with pytest.raises(ProbeError, match=message):
        await probe.run()

    assert factory.clients[0].disconnects == 1


async def test_a_hanging_probe_times_out(tmp_path: Path) -> None:
    factory = FakeProbeFactory(hang=True)
    probe = UsageProbe(factory, tmp_path, timeout=timedelta(milliseconds=20))

    with pytest.raises(ProbeError, match="timed out"):
        await probe.run()

    assert factory.clients[0].disconnects == 1


async def test_closing_survives_a_failing_disconnect(tmp_path: Path) -> None:
    factory = FakeProbeFactory(replies=[answer()])
    probe = UsageProbe(factory, tmp_path)
    await probe.run()
    factory.clients[0].disconnect_error = RuntimeError("already gone")
    await probe.close()
    await probe.close()

    # The failed close still let the client go: the second close has nothing to close.
    assert factory.clients[0].disconnects == 1
