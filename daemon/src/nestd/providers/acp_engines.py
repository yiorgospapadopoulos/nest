"""The engines Nest runs over the Agent Client Protocol (B107).

ACP is JSON-RPC 2.0 over the agent's stdin and stdout. Each engine here is one Nest engine
on the generic ACP provider. An open one is fetched from npm into Nest's own folder with
Nest's install (`bundled`); one that is not on npm runs from the user's own install of it
(`user_install`). A fetched engine's version here is the one the base environment runs; a
prepared environment (`nestd/updates`) names newer ones in its manifest, applied below.

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

How long an engine waits for one MCP tool call (`mcp_tool_timeout`, B112) bounds Nest's
tools that wait on the user (`ask_user`) or on a called pixie. ACP's `mcpServers` carry no
timeout, so it is the engine's own: OpenCode's comes from its config, which Nest sets to
a week for every run (`experimental.mcp_timeout`, found in its 1.19.4 code; it covers the
user's own MCP servers in Nest's runs too); Gemini CLI gives a server added over ACP its
default of 10 minutes (0.65.0 code), which nothing changes; Cursor's is not known, so the
MCP client's default of a minute is assumed.
"""

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path
from typing import Literal

from nestd.updates.manifest import read_manifest

type Delivery = Literal["bundled", "user_install"]
type SignIn = Literal["api_key", "terminal"]

# The MCP client's own default for one request, where an engine sets none.
MCP_DEFAULT_TIMEOUT = timedelta(minutes=1)
# Past the week a question waits (as Claude's do), so the question gives up first.
OPENCODE_MCP_TIMEOUT = timedelta(days=7, hours=1)


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
    # Added while Nest must decide every command (`SessionSpec.nest_decides`): pixie chats,
    # habit runs, chats a pixie started and Autopilot.
    guarded_env: Mapping[str, str] = field(default_factory=dict[str, str])
    # Added while the user has not let agents push (`SessionSpec.guard_subagents`): the
    # engine's own rules that stop its subagents' pushes (B127), before `guarded_env`.
    subagent_env: Mapping[str, str] = field(default_factory=dict[str, str])
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
    # How long the engine waits for one call of an MCP tool, Nest's included.
    mcp_tool_timeout: timedelta = MCP_DEFAULT_TIMEOUT

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
_OPENCODE_PRIMARY = ("build", "plan")
_OPENCODE_SUBAGENTS = ("general", "explore")
_OPENCODE_GUARDED_RULES: dict[str, object] = {
    **_OPENCODE_RULES,
    "task": {"*": "deny", "general": "allow", "explore": "allow"},
}
# A subagent's shell commands that push or write pull requests, while agents may not push
# (B127). Its questions never reach Nest (OpenCode 1.19.5 drops a child session's in
# `acp/permission.ts`), so only a deny stops one. Each simple command's text is matched,
# `*` matching anything, so `git -C x push` is caught too, and some reads (`gh pr view`)
# that such a subagent could not have run anyway.
_OPENCODE_SUBAGENT_BASH = dict.fromkeys(
    (
        *("*git*push*", "*git*send-pack*", "*git*http-push*", "*gh*pr*"),
        *("*gh*api*", "*gh*repo*sync*", "*gh*auth*token*", "*gh*alias*"),
    ),
    "deny",
)
# Read after every config file, so Nest's timeout wins (in milliseconds).
_OPENCODE_CONFIG = {
    "experimental": {"mcp_timeout": int(OPENCODE_MCP_TIMEOUT.total_seconds() * 1000)}
}
_OPENCODE_SUBAGENT_CONFIG = {
    **_OPENCODE_CONFIG,
    "agent": {
        name: {"permission": {"bash": _OPENCODE_SUBAGENT_BASH}} for name in _OPENCODE_SUBAGENTS
    },
}
_OPENCODE_GUARDED_CONFIG = {
    **_OPENCODE_CONFIG,
    "default_agent": "build",
    "agent": {
        **{name: {"permission": _OPENCODE_GUARDED_RULES} for name in _OPENCODE_PRIMARY},
        **{
            name: {
                "permission": {
                    **_OPENCODE_GUARDED_RULES,
                    "bash": {"*": "ask", **_OPENCODE_SUBAGENT_BASH},
                }
            }
            for name in _OPENCODE_SUBAGENTS
        },
    },
}
# Gemini's system settings win over the user's and the project's; Nest's file turns off
# "always allow", so every call is asked (written next to the engine, `system_settings`).
GEMINI_SYSTEM_SETTINGS = '{"security":{"disableAlwaysAllow":true}}'
GEMINI_SYSTEM_SETTINGS_ENV = "GEMINI_CLI_SYSTEM_SETTINGS_PATH"
# The same while agents may not push (B127), with an admin policy, which outranks every
# other, that denies the pushes of Gemini's own subagent that runs commands: its questions
# never reach Nest (Gemini CLI 0.66.0 asks them on its own bus, `local-executor.ts`).
GEMINI_SUBAGENT_SETTINGS = "gemini-subagent-settings.json"
GEMINI_SUBAGENT_POLICY = "gemini-subagent-pushes.toml"
_GEMINI_SUBAGENTS = ("generalist",)
_GEMINI_PUSHES = (
    r"\bgit\b.*\b(?:push|send-pack|http-push)\b"
    r"|\bgh\b.*\b(?:pr|api|repo\s+sync|auth\s+token|alias)\b"
)


def gemini_subagent_files(folder: Path, reason: str) -> dict[str, str]:
    """The system settings and the policy they name, by file name in `folder`."""
    rules = [
        "\n".join(
            (
                "[[rule]]",
                'toolName = "run_shell_command"',
                f"subagent = {json.dumps(name)}",
                f"commandRegex = {json.dumps(_GEMINI_PUSHES)}",
                'decision = "deny"',
                "priority = 999",
                f"denyMessage = {json.dumps(reason)}",
            )
        )
        for name in _GEMINI_SUBAGENTS
    ]
    settings = {
        **json.loads(GEMINI_SYSTEM_SETTINGS),
        "adminPolicyPaths": [str(folder / GEMINI_SUBAGENT_POLICY)],
    }
    return {
        GEMINI_SUBAGENT_SETTINGS: json.dumps(settings),
        GEMINI_SUBAGENT_POLICY: "\n\n".join(rules) + "\n",
    }


GEMINI_KEY_ENV = "GEMINI_API_KEY"

OPENCODE = AcpEngine(
    id="opencode",
    name="OpenCode",
    package="opencode-ai",
    version="1.19.5",
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
        "OPENCODE_CONFIG_CONTENT": json.dumps(_OPENCODE_CONFIG),
    },
    guarded_env={"OPENCODE_CONFIG_CONTENT": json.dumps(_OPENCODE_GUARDED_CONFIG)},
    subagent_env={"OPENCODE_CONFIG_CONTENT": json.dumps(_OPENCODE_SUBAGENT_CONFIG)},
    login_command="opencode auth login",
    # It runs its free models signed out, so only its login file says it is signed in.
    auth_file="opencode/auth.json",
    # An added account keeps its login and sessions apart (data, state) but shares the
    # user's config folder, so the user's setup and the git config its commands read stay.
    home_env={"XDG_DATA_HOME": "data", "XDG_STATE_HOME": "state"},
    mcp_tool_timeout=OPENCODE_MCP_TIMEOUT,
)
GEMINI = AcpEngine(
    id="gemini",
    name="Gemini CLI",
    package="@google/gemini-cli",
    version="0.66.0",
    executable="gemini",
    args=("--acp", "--approval-mode", "default"),
    delivery="bundled",
    sign_in="api_key",
    tested=True,
    git_guard=True,
    home_env={"GEMINI_CLI_HOME": ""},
    mcp_tool_timeout=timedelta(minutes=10),
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
# As the base environment runs them.
BASE_ENGINES: tuple[AcpEngine, ...] = (OPENCODE, GEMINI, CURSOR)


def in_environment(engines: tuple[AcpEngine, ...], prefix: Path) -> tuple[AcpEngine, ...]:
    """`engines` at the versions the environment at `prefix` holds; the base holds none."""
    manifest = read_manifest(prefix)
    if manifest is None:
        return engines
    return tuple(
        replace(engine, version=manifest.packages.get(engine.id, engine.version))
        if engine.delivery == "bundled"
        else engine
        for engine in engines
    )


ACP_ENGINES: tuple[AcpEngine, ...] = in_environment(BASE_ENGINES, Path(sys.prefix))
ACP_ENGINE_IDS: frozenset[str] = frozenset(engine.id for engine in ACP_ENGINES)


def acp_engine(engine_id: str) -> AcpEngine | None:
    return next((engine for engine in ACP_ENGINES if engine.id == engine_id), None)


def account_env(engine: AcpEngine, home: Path) -> dict[str, str]:
    """The variables that run `engine` on the account folder `home`."""
    return {name: str(home / sub) if sub else str(home) for name, sub in engine.home_env.items()}
