"""What "Always allow" applies, and in words (IMP-06, B59).

When the engine asks, it suggests the rules that would stop it asking again, each with
where Claude Code keeps it (the session, or a settings file). "Always allow" applies them
as they are. When it suggests none, Nest allows that exact call for the rest of the run:
the command, the file or the web domain, in Claude Code's permission rule syntax.
"""

from urllib.parse import urlsplit

from claude_agent_sdk import PermissionUpdate
from claude_agent_sdk.types import PermissionRuleValue
from pydantic import JsonValue

_MODES = {"acceptEdits": "Auto-accept edits"}
# Edit rules cover every tool that edits files, so each is allowed as an Edit rule.
_EDIT_TOOLS = {
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "Write": "file_path",
    "NotebookEdit": "notebook_path",
}


def always_rule(suggestions: list[PermissionUpdate]) -> str | None:
    """The suggested rules as text, such as `Bash(npm test:*)`; None when nothing usable."""
    parts: list[str] = []
    for update in suggestions:
        if update.type == "addRules" and update.behavior in (None, "allow"):
            parts.extend(
                f"{rule.tool_name}({rule.rule_content})" if rule.rule_content else rule.tool_name
                for rule in update.rules or []
            )
        elif update.type == "addDirectories":
            parts.extend(f"access to {directory}" for directory in update.directories or [])
        elif update.type == "setMode" and update.mode is not None:
            parts.append(_MODES.get(update.mode, f"{update.mode} mode"))
    return ", ".join(parts) or None


def always_updates(
    tool_name: str, tool_input: dict[str, JsonValue], suggestions: list[PermissionUpdate]
) -> tuple[list[PermissionUpdate], str]:
    """The updates "Always allow" applies and the rule they make, in words."""
    suggested = always_rule(suggestions)
    if suggested is not None:
        return list(suggestions), suggested
    rule, words = _exact_rule(tool_name, tool_input)
    update = PermissionUpdate(
        type="addRules", rules=[rule], behavior="allow", destination="session"
    )
    return [update], words


def _exact_rule(
    tool_name: str, tool_input: dict[str, JsonValue]
) -> tuple[PermissionRuleValue, str]:
    """A rule for this call alone where the syntax can name it, else for the tool."""
    if tool_name == "Bash":
        command = _text(tool_input.get("command"))
        if command:
            return _rule("Bash", _literal(command), command)
    elif tool_name in _EDIT_TOOLS or tool_name == "Read":
        path = _text(tool_input.get(_EDIT_TOOLS.get(tool_name, "file_path")))
        if path:
            # `//` starts an absolute path in a rule; a single `/` is the project's root.
            content = f"/{path}" if path.startswith("/") else path
            return _rule("Edit" if tool_name in _EDIT_TOOLS else "Read", content, path)
    elif tool_name == "WebFetch":
        host = urlsplit(_text(tool_input.get("url"))).hostname
        if host:
            return _rule("WebFetch", f"domain:{host}", f"domain:{host}")
    return PermissionRuleValue(tool_name), tool_name


def _rule(tool: str, content: str, shown: str) -> tuple[PermissionRuleValue, str]:
    return PermissionRuleValue(tool, content), f"{tool}({shown})"


def _literal(command: str) -> str:
    """A command as a rule matching only itself: a star would match anything, so it and
    backslashes are escaped (a rule without a star is compared as it is).
    """
    if "*" not in command:
        return command
    return command.replace("\\", "\\\\").replace("*", "\\*")


def _text(value: JsonValue) -> str:
    return value.strip() if isinstance(value, str) else ""
