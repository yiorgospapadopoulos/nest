"""IMP-06: "Always allow" applies the rules Claude Code suggests, shown in words."""

from pathlib import Path

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionUpdate, ToolPermissionContext
from claude_agent_sdk.types import PermissionRuleValue

from harness.providers.base import PermissionDecision, PermissionRequest, SessionSpec
from harness.providers.claude_rules import always_rule
from tests.test_claude_provider import Opened, ScriptedHandler

NPM_TEST = PermissionUpdate(
    type="addRules",
    rules=[PermissionRuleValue("Bash", "npm test:*")],
    behavior="allow",
    destination="localSettings",
)


@pytest.mark.parametrize(
    ("suggestions", "rule"),
    [
        ([NPM_TEST], "Bash(npm test:*)"),
        (
            [
                PermissionUpdate(
                    type="addRules",
                    rules=[PermissionRuleValue("WebFetch"), PermissionRuleValue("Read", "/x/**")],
                    destination="session",
                ),
                PermissionUpdate(
                    type="addDirectories", directories=["/data/a"], destination="session"
                ),
                PermissionUpdate(type="setMode", mode="acceptEdits", destination="session"),
                PermissionUpdate(type="setMode", mode="plan", destination="session"),
            ],
            "WebFetch, Read(/x/**), access to /data/a, Auto-accept edits, plan mode",
        ),
        (
            [
                PermissionUpdate(
                    type="addRules", rules=[PermissionRuleValue("Bash")], behavior="deny"
                ),
                PermissionUpdate(type="removeRules", rules=[PermissionRuleValue("Bash")]),
                PermissionUpdate(type="addRules"),
                PermissionUpdate(type="addDirectories"),
                PermissionUpdate(type="setMode"),
            ],
            None,
        ),
        ([], None),
    ],
)
def test_suggestions_read_as_a_rule(suggestions: list[PermissionUpdate], rule: str | None) -> None:
    assert always_rule(suggestions) == rule


async def test_always_applies_the_suggestions_with_their_destination(tmp_path: Path) -> None:
    handler = ScriptedHandler(PermissionDecision("allow", always=True))
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"), handler)
    assert client.options.can_use_tool is not None
    context = ToolPermissionContext(suggestions=[NPM_TEST], title="Run npm test?")

    result = await client.options.can_use_tool("Bash", {"command": "npm test"}, context)

    assert result == PermissionResultAllow(updated_permissions=[NPM_TEST])
    assert handler.requests == [
        PermissionRequest(
            "Bash", {"command": "npm test"}, "Run npm test?", always_rule="Bash(npm test:*)"
        )
    ]


@pytest.mark.parametrize(
    ("decision", "suggestions"),
    [
        # Allowed once: the suggestions are left for next time.
        (PermissionDecision("allow"), [NPM_TEST]),
        # Nothing suggested: harness allows the tool by name for the session instead.
        (PermissionDecision("allow", always=True), []),
    ],
)
async def test_other_allows_apply_no_rules(
    tmp_path: Path, decision: PermissionDecision, suggestions: list[PermissionUpdate]
) -> None:
    handler = ScriptedHandler(decision)
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"), handler)
    assert client.options.can_use_tool is not None

    result = await client.options.can_use_tool(
        "Bash", {"command": "npm test"}, ToolPermissionContext(suggestions=suggestions)
    )

    assert result == PermissionResultAllow()
