"""IMP-06: "Always allow" applies the rules Claude Code suggests, shown in words."""

from pathlib import Path

import pytest
from claude_agent_sdk import PermissionResultAllow, PermissionUpdate, ToolPermissionContext
from claude_agent_sdk.types import PermissionRuleValue
from pydantic import JsonValue

from nestd.providers.base import PermissionDecision, PermissionRequest, SessionSpec
from nestd.providers.claude_rules import always_rule
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


async def test_allowed_once_leaves_the_suggestions_for_next_time(tmp_path: Path) -> None:
    handler = ScriptedHandler(PermissionDecision("allow"))
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"), handler)
    assert client.options.can_use_tool is not None

    result = await client.options.can_use_tool(
        "Bash", {"command": "npm test"}, ToolPermissionContext(suggestions=[NPM_TEST])
    )

    assert result == PermissionResultAllow()


def session_rule(tool: str, content: str | None = None) -> PermissionUpdate:
    return PermissionUpdate(
        type="addRules",
        rules=[PermissionRuleValue(tool, content)],
        behavior="allow",
        destination="session",
    )


@pytest.mark.parametrize(
    ("tool", "tool_input", "update", "rule"),
    [
        # That exact command, not every command (B59).
        (
            "Bash",
            {"command": "  rm -rf build  "},
            session_rule("Bash", "rm -rf build"),
            "Bash(rm -rf build)",
        ),
        # A star would match other commands: it is escaped, and so are backslashes.
        (
            "Bash",
            {"command": r"ls *.py \\ x"},
            session_rule("Bash", r"ls \*.py \\\\ x"),
            r"Bash(ls *.py \\ x)",
        ),
        # File tools: that file, as an absolute path rule; every edit tool is an Edit rule.
        (
            "Edit",
            {"file_path": "/repo/a.py"},
            session_rule("Edit", "//repo/a.py"),
            "Edit(/repo/a.py)",
        ),
        (
            "Write",
            {"file_path": "/repo/b.py"},
            session_rule("Edit", "//repo/b.py"),
            "Edit(/repo/b.py)",
        ),
        (
            "MultiEdit",
            {"file_path": "rel/c.py"},
            session_rule("Edit", "rel/c.py"),
            "Edit(rel/c.py)",
        ),
        (
            "NotebookEdit",
            {"notebook_path": "/repo/n.ipynb"},
            session_rule("Edit", "//repo/n.ipynb"),
            "Edit(/repo/n.ipynb)",
        ),
        (
            "Read",
            {"file_path": "/etc/hosts"},
            session_rule("Read", "//etc/hosts"),
            "Read(/etc/hosts)",
        ),
        (
            "WebFetch",
            {"url": "https://Docs.Example.com/a?b=1", "prompt": "x"},
            session_rule("WebFetch", "domain:docs.example.com"),
            "WebFetch(domain:docs.example.com)",
        ),
        # Without the part a rule names, or for other tools: the tool, for this session.
        ("WebFetch", {"url": "not a url"}, session_rule("WebFetch"), "WebFetch"),
        ("Bash", {"command": "  "}, session_rule("Bash"), "Bash"),
        ("Read", {"file_path": 3}, session_rule("Read"), "Read"),
        (
            "mcp__github__create_issue",
            {"title": "x"},
            session_rule("mcp__github__create_issue"),
            "mcp__github__create_issue",
        ),
    ],
)
async def test_always_without_a_suggestion_allows_that_exact_call(
    tmp_path: Path,
    tool: str,
    tool_input: dict[str, JsonValue],
    update: PermissionUpdate,
    rule: str,
) -> None:
    handler = ScriptedHandler(PermissionDecision("allow", always=True))
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"), handler)
    assert client.options.can_use_tool is not None

    result = await client.options.can_use_tool(tool, tool_input, ToolPermissionContext())

    assert result == PermissionResultAllow(updated_permissions=[update])
    assert [request.always_rule for request in handler.requests] == [rule]
