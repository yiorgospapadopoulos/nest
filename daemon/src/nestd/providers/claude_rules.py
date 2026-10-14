"""Claude Code's permission suggestions in words, for "Always allow" (IMP-06).

When the engine asks, it suggests the rules that would stop it asking again, each with
where Claude Code keeps it (the session, or a settings file). "Always allow" applies them
as they are; this module only says what they are.
"""

from claude_agent_sdk import PermissionUpdate

_MODES = {"acceptEdits": "Auto-accept edits"}


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
