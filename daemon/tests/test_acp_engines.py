"""OpenCode's rules from the catalogue keep asking, whatever the user's own settings allow
(B107). OpenCode's own merge is modelled from its 1.18 code and was checked live: config
files are merged key by key (a key the user has keeps its place), the rules then run in
order and the last one matching a tool's name wins, and an MCP tool is `<server>_<tool>`.
"""

import json
from collections.abc import Mapping
from fnmatch import fnmatchcase

import pytest

from nestd.providers.acp_engines import OPENCODE

# OpenCode's built-in agent's own rules come first.
_DEFAULTS = [("*", "allow"), ("question", "deny")]


def merged(user: Mapping[str, object], ours: Mapping[str, object]) -> dict[str, object]:
    return {**user, **ours}


def action(rules: dict[str, object], tool: str) -> str:
    ruleset = _DEFAULTS + [
        (key, value if isinstance(value, str) else str(value.get("*", "ask")))  # type: ignore[union-attr]
        for key, value in rules.items()
    ]
    return next(found for key, found in reversed(ruleset) if fnmatchcase(tool, key))


@pytest.mark.parametrize("tool", ["echo_echo", "github_create_pull_request", "bash", "deploy"])
def test_a_users_allow_in_their_config_still_asks(tool: str) -> None:
    ours = json.loads(OPENCODE.env["OPENCODE_PERMISSION"])
    user = {"*": "allow", "echo_*": "allow", "github_*": "allow", "bash": "allow"}

    assert action(merged(user, ours), tool) == "ask"


@pytest.mark.parametrize("agent", ["build", "plan", "general", "explore"])
@pytest.mark.parametrize("tool", ["echo_echo", "bash"])
def test_a_guarded_run_asks_whatever_the_users_agent_settings_allow(agent: str, tool: str) -> None:
    config = json.loads(OPENCODE.guarded_env["OPENCODE_CONFIG_CONTENT"])
    ours = config["agent"][agent]["permission"]
    user_agent = {"bash": "allow", "echo_*": "allow"}

    assert config["default_agent"] == "build"
    assert action(merged(user_agent, ours), tool) == "ask"


def test_a_guarded_run_calls_only_the_built_in_subagents() -> None:
    config = json.loads(OPENCODE.guarded_env["OPENCODE_CONFIG_CONTENT"])

    assert config["agent"]["build"]["permission"]["task"] == {
        "*": "deny",
        "general": "allow",
        "explore": "allow",
    }


def test_opencodes_reading_tools_stay_allowed() -> None:
    ours = json.loads(OPENCODE.env["OPENCODE_PERMISSION"])

    for tool in ("read", "glob", "grep", "todowrite"):
        assert action(ours, tool) == "allow"
