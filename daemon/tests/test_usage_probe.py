from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from nestd.providers.base import RunAccount, ScopedWindow, TokenUsage, UsageInfo, UsageWindow
from nestd.providers.claude_messages import usage_info
from nestd.usage.plan_read import plan_usage
from nestd.usage.probe import (
    MAX_PROBES_PER_CLIENT,
    PROBE_PROMPT,
    ProbeError,
    UsageProbe,
    probe_options,
)
from tests.fake_probe import FakeProbeFactory, answer, plan, result


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


async def test_a_probe_reads_the_plan_usage_for_free(tmp_path: Path) -> None:
    """B142: Claude Code reports the plan's windows without a turn, so no tokens are used."""
    factory = FakeProbeFactory(plans=[plan(five_hour=35, seven_day=None), plan(36)])
    probe = UsageProbe(factory, tmp_path)

    first = await probe.run()
    second = await probe.run()

    assert first.limits == UsageInfo(
        five_hour=UsageWindow(utilization=0.35, resets_at=None),
        seven_day=None,
        complete=True,
    )
    assert first.tokens == TokenUsage()
    assert second.limits is not None
    assert second.limits.seven_day == UsageWindow(utilization=0.12, resets_at=None)
    client = factory.clients[0]
    assert client.prompts == []
    assert client.control is not None
    assert client.control.requests == [{"subtype": "get_usage", "skip_behaviors": True}] * 2
    assert client.disconnects == 0


@pytest.mark.parametrize(
    "refusal",
    [
        RuntimeError("get_usage is not supported in this context"),
        {"rate_limits_available": False, "rate_limits": None},
        plan(five_hour=None, seven_day=None),
        {"rate_limits_available": True, "rate_limits": {"seven_day": {"utilization": "lots"}}},
    ],
)
async def test_a_probe_sends_its_turn_when_the_free_read_gives_nothing(
    tmp_path: Path, refusal: dict[str, object] | Exception
) -> None:
    factory = FakeProbeFactory(replies=[answer(0.42, 0.12)], plans=[refusal])
    probe = UsageProbe(factory, tmp_path)

    outcome = await probe.run()

    assert outcome.limits is not None
    assert outcome.limits.five_hour is not None
    assert outcome.limits.five_hour.utilization == 0.42
    assert outcome.tokens == TokenUsage(input_tokens=450, output_tokens=2)
    assert factory.clients[0].prompts == [PROBE_PROMPT]


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


async def test_a_probe_on_another_account_opens_its_own_client(tmp_path: Path) -> None:
    """B98: the client runs on the account asked for, with its profile; one on another
    account is closed first.
    """
    factory = FakeProbeFactory(replies=[answer(0.1), answer(0.2), answer(0.3)])
    probe = UsageProbe(factory, tmp_path)
    work = RunAccount("0123456789ab", {"CLAUDE_CONFIG_DIR": str(tmp_path / "work")})

    await probe.run()
    await probe.run(work)
    await probe.run(work)

    first, second = factory.clients
    assert first.options.env == {}
    assert first.disconnects == 1
    assert second.options.env == {"CLAUDE_CONFIG_DIR": str(tmp_path / "work")}
    assert second.prompts == [PROBE_PROMPT, PROBE_PROMPT]


FABLE_RESET = datetime(2026, 11, 16, 11, tzinfo=UTC)


def _real_plan(**changes: object) -> dict[str, object]:
    """B161: the shape of a real `get_usage` answer (Claude Code 2.1.317), trimmed."""
    limits: dict[str, object] = {
        "five_hour": None,
        "seven_day": {"utilization": 25, "resets_at": "2026-11-16T10:59:59+00:00"},
        "seven_day_oauth_apps": None,
        "seven_day_opus": None,
        "seven_day_sonnet": {"utilization": 3, "resets_at": None},
        "seven_day_cowork": None,
        "extra_usage": {"is_enabled": False, "utilization": None},
        "limits": [{"kind": "weekly_all", "percent": 25}],
        "model_scoped": [
            {"display_name": "Fable", "utilization": 40, "resets_at": "2026-11-16T11:00:00+00:00"}
        ],
        **changes,
    }
    return {"subscription_type": "max", "rate_limits_available": True, "rate_limits": limits}


def test_the_plan_read_keeps_every_per_model_window_by_name() -> None:
    info = plan_usage(_real_plan())

    assert info is not None
    assert info.five_hour is None
    assert info.seven_day is not None
    assert info.seven_day.utilization == 0.25
    assert info.scoped == [
        ScopedWindow(label="Sonnet", utilization=0.03, resets_at=None),
        ScopedWindow(label="Fable", utilization=0.4, resets_at=FABLE_RESET),
    ]
    assert info.complete


def test_a_window_without_a_number_never_drops_the_whole_answer() -> None:
    """B161 regression: a null `utilization` in one window failed the whole read, so the
    probe sent a turn instead.
    """
    info = plan_usage(
        _real_plan(
            five_hour={"utilization": None, "resets_at": None},
            model_scoped=[
                {"display_name": "Fable", "utilization": None, "resets_at": None},
                {"utilization": 5},
                {"display_name": "Haiku", "utilization": 7, "resets_at": None},
            ],
        )
    )

    assert info is not None
    assert info.five_hour is None
    assert info.seven_day is not None
    assert [w.label for w in info.scoped] == ["Sonnet", "Haiku"]
    assert info.unread == {"five_hour", "scoped:Fable"}


def test_a_turn_report_brings_the_fable_window() -> None:
    """B161: a turn names only the per-model bucket Claude Code calls the Fable limit."""
    raw = {
        "unifiedWindows": {
            "seven_day_overage_included": {"utilization": 0.4, "resetsAt": 1794826800}
        }
    }

    info = usage_info(raw)

    assert info is not None
    assert (info.five_hour, info.seven_day) == (None, None)
    assert info.scoped == [
        ScopedWindow(
            label="Fable", utilization=0.4, resets_at=datetime.fromtimestamp(1794826800, UTC)
        )
    ]
    assert not info.complete
