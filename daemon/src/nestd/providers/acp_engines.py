"""The engines Nest runs over the Agent Client Protocol (B107), each pinned to a tested version.

ACP is JSON-RPC 2.0 over the agent's stdin and stdout. Each engine here is one Nest engine
on the generic ACP provider. An open one is fetched from npm into Nest's own folder with
Nest's install (`bundled`); one that is not on npm runs from the user's own install of it
(`user_install`). Updating a pinned version is a normal Nest change with its tests.

Nest makes each engine ask before shell commands, edits, access outside its folder and
the user's own MCP tools, and answers every request itself (`git_guard`). Where the spike
could not confirm that an engine can be made to ask, `git_guard` is False: it still runs,
with a warning in Settings.

OpenCode (checked in its 1.18 code and live, B107): its permission rules are matched by tool
name, the last matching rule winning, and an MCP tool's name is `<server>_<tool>`. Every run
gets `OPENCODE_PERMISSION`, which comes after the user's and the project's `permission`
settings: everything asks (`*`, and `*_*` after any narrower rule of the user's, which
catches every MCP tool) except OpenCode's own tools that only read or keep its to-do list.
The user's own agent settings (`agent.<name>.permission`) come after that, so a guarded
run (`guarded_env`) also gets the same rules for OpenCode's built-in agents through
`OPENCODE_CONFIG_CONTENT`, read after every config file, runs as the `build` agent, and may
call only the built-in subagents. What is left: a user's rule for a single tool name that
comes after their own `*` in their own agent settings, and plugins, which run their own code.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

type Delivery = Literal["bundled", "user_install"]
type SignIn = Literal["api_key", "terminal"]


@dataclass(frozen=True)
class AcpEngine:
    id: str
    name: str
    # npm package and the pinned version; None for an engine Nest does not fetch.
    package: str | None
    version: str | None
    # The executable inside the installed package's `node_modules/.bin`, or on PATH.
    executable: str
    args: tuple[str, ...]
    delivery: Delivery
    sign_in: SignIn
    # Live-tested by Nest; False shows "untested" in Settings.
    tested: bool
    git_guard: bool
    # Environment every run of the engine gets, whatever the user's own settings say.
    env: Mapping[str, str] = field(default_factory=dict[str, str])
    # Added for a guarded run (D013): pixie chats, habit runs and chats a pixie started.
    guarded_env: Mapping[str, str] = field(default_factory=dict[str, str])
    # The command that signs in, in Terminal: required for `sign_in == "terminal"`.
    login_command: str | None = None
    # The engine's own login file, relative to XDG_DATA_HOME: signed in while it holds an
    # entry. For an engine that answers ACP signed out, so the probe cannot tell.
    auth_file: str | None = None
    # The variables that point the engine at an added account's own folder, by the
    # subfolder of the account folder they name ("" for the folder itself).
    home_env: Mapping[str, str] = field(default_factory=dict[str, str])
    # Where the engine is when the user installed it themselves (`user_install`).
    user_paths: tuple[str, ...] = ()

    @property
    def several_accounts(self) -> bool:
        return bool(self.home_env)


# OpenCode asks before everything but reading and its to-do list, whatever the user's or the
# project's opencode.json allow (verified live in B107). In order: the later rule wins.
_OPENCODE_RULES: dict[str, object] = {
    "*": "ask",
    "read": {"*": "allow", "*.env": "ask", "*.env.*": "ask", "*.env.example": "allow"},
    "glob": "allow",
    "grep": "allow",
    "list": "allow",
    "lsp": "allow",
    "todowrite": "allow",
    "todoread": "allow",
    "skill": "allow",
    "task": "allow",
    "invalid": "allow",
    "bash": "ask",
    "edit": "ask",
    "external_directory": "ask",
    "webfetch": "ask",
    "websearch": "ask",
    # After any narrower rule of the user's: every MCP tool is `<server>_<tool>`.
    "*_*": "ask",
}
# A guarded run's agents may call only the built-in subagents, which get the rules too.
_OPENCODE_AGENTS = ("build", "plan", "general", "explore")
_OPENCODE_GUARDED_RULES: dict[str, object] = {
    **_OPENCODE_RULES,
    "task": {"*": "deny", "general": "allow", "explore": "allow"},
}
_OPENCODE_GUARDED_CONFIG = {
    "default_agent": "build",
    "agent": {name: {"permission": _OPENCODE_GUARDED_RULES} for name in _OPENCODE_AGENTS},
}
# Gemini's system settings win over the user's and the project's; Nest's file turns off
# "always allow", so every call is asked (written next to the engine, `system_settings`).
GEMINI_SYSTEM_SETTINGS = '{"security":{"disableAlwaysAllow":true}}'
GEMINI_SYSTEM_SETTINGS_ENV = "GEMINI_CLI_SYSTEM_SETTINGS_PATH"
GEMINI_KEY_ENV = "GEMINI_API_KEY"

OPENCODE = AcpEngine(
    id="opencode",
    name="OpenCode",
    package="opencode-ai",
    version="1.19.4",
    executable="opencode",
    args=("acp",),
    delivery="bundled",
    sign_in="terminal",
    tested=True,
    git_guard=True,
    env={
        "OPENCODE_PERMISSION": json.dumps(_OPENCODE_RULES),
        "OPENCODE_DISABLE_AUTOUPDATE": "1",
        # Else it lists the user's Claude Code skills as its own commands.
        "OPENCODE_DISABLE_CLAUDE_CODE": "1",
    },
    guarded_env={"OPENCODE_CONFIG_CONTENT": json.dumps(_OPENCODE_GUARDED_CONFIG)},
    login_command="opencode auth login",
    # It runs its free models signed out, so only its login file says it is signed in.
    auth_file="opencode/auth.json",
    # An added account keeps its login and sessions apart (data, state) but shares the
    # user's config folder, so the user's setup and the git config its commands read stay.
    home_env={"XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state"},
)
GEMINI = AcpEngine(
    id="gemini",
    name="Gemini CLI",
    package="@google/gemini-cli",
    version="0.65.0",
    executable="gemini",
    args=("--acp", "--approval-mode", "default"),
    delivery="bundled",
    sign_in="api_key",
    tested=True,
    git_guard=True,
    home_env={"GEMINI_CLI_HOME": ""},
)
CURSOR = AcpEngine(
    id="cursor",
    name="Cursor agent",
    package=None,
    version=None,
    executable="agent",
    args=("acp",),
    delivery="user_install",
    sign_in="terminal",
    tested=False,
    git_guard=False,
    login_command="agent login",
    user_paths=("~/.local/bin/agent",),
)
ACP_ENGINES: tuple[AcpEngine, ...] = (OPENCODE, GEMINI, CURSOR)
ACP_ENGINE_IDS: frozenset[str] = frozenset(engine.id for engine in ACP_ENGINES)


def acp_engine(engine_id: str) -> AcpEngine | None:
    return next((engine for engine in ACP_ENGINES if engine.id == engine_id), None)


def account_env(engine: AcpEngine, home: Path) -> dict[str, str]:
    """The variables that run `engine` on the account folder `home`."""
    return {name: str(home / sub) if sub else str(home) for name, sub in engine.home_env.items()}
