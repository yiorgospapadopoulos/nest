from typing import Any

from claude_agent_sdk import SystemMessage

from harness.providers.base import AgentInfo, CommandCatalog, ContextUsage, SlashCommand
from harness.providers.claude_commands import context_usage, described_catalog, init_catalog
from harness.providers.claude_messages import TurnOutput, translate
from harness.providers.claude_thinking import ThinkingTimer
from tests.recording_sink import RecordingSink

SERVER_INFO: dict[str, Any] = {
    "commands": [
        {"name": "review", "description": "Review a pull request", "argumentHint": "<pr>"},
        {"name": "compact", "description": "Clear history but keep a summary", "argumentHint": ""},
        {"name": "Zed:open", "description": "", "aliases": [], "builtin": True},
        {"name": "__remote-workflow", "description": "internal"},
        {"description": "no name"},
        "not an object",
    ],
    "agents": [{"name": "Explore", "description": "Search code"}, {"name": "Plan"}, 7],
    "models": [],
}


def test_described_catalogs_keep_descriptions_and_hints_sorted_by_name() -> None:
    assert described_catalog(SERVER_INFO) == CommandCatalog(
        commands=[
            SlashCommand(name="compact", description="Clear history but keep a summary"),
            SlashCommand(name="review", description="Review a pull request", argument_hint="<pr>"),
            SlashCommand(name="Zed:open"),
        ],
        agents=[AgentInfo(name="Explore", description="Search code"), AgentInfo(name="Plan")],
    )


def test_described_catalogs_need_something_to_report() -> None:
    assert described_catalog(None) is None
    assert described_catalog({"commands": "nope", "agents": []}) is None
    assert described_catalog({"agents": [{"name": "Plan"}]}) == CommandCatalog(
        agents=[AgentInfo(name="Plan")]
    )


def test_init_catalogs_name_commands_skills_and_agents_once() -> None:
    data = {
        "slash_commands": ["review", "compact", "__internal", 3, ""],
        "skills": ["pdf", "review"],
        "agents": ["Plan", "Explore", "Plan"],
    }

    assert init_catalog(data) == CommandCatalog(
        commands=[
            SlashCommand(name="compact"),
            SlashCommand(name="pdf"),
            SlashCommand(name="review"),
        ],
        agents=[AgentInfo(name="Explore"), AgentInfo(name="Plan")],
        partial=True,
    )
    assert init_catalog({"session_id": "s"}) is None


def test_context_usage_reads_percent_tokens_and_limit() -> None:
    raw: dict[str, Any] = {
        "percentage": 41.5,
        "totalTokens": 83000,
        "maxTokens": 200000,
        "categories": [],
    }

    assert context_usage(raw) == ContextUsage(percent=41.5, used=83000, limit=200000)
    assert context_usage({"percentage": 3}) is None
    assert context_usage(None) is None


async def test_the_init_message_and_command_changes_report_catalogs() -> None:
    sink = RecordingSink()
    timer = ThinkingTimer()
    output = TurnOutput()

    await translate(
        SystemMessage(subtype="init", data={"session_id": "s", "slash_commands": ["compact"]}),
        sink,
        timer,
        output,
    )
    await translate(
        SystemMessage(subtype="commands_changed", data=SERVER_INFO), sink, timer, output
    )
    await translate(
        SystemMessage(subtype="commands_changed", data={"commands": []}), sink, timer, output
    )

    reported = [value for name, value in sink.calls if name == "commands"]
    assert reported == [
        CommandCatalog(commands=[SlashCommand(name="compact")], partial=True),
        described_catalog(SERVER_INFO),
    ]
