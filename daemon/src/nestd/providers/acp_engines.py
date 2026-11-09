"""The engines Nest runs over the Agent Client Protocol (B107, B153).

ACP is JSON-RPC 2.0 over the agent's stdin and stdout. Each engine here is one Nest engine
on the generic ACP provider, and each is its vendor's own, as the ACP Registry lists it
(`engine/acp_registry.py`); no community adapter (D136, D182). One on npm is fetched into
Nest's own folder with Nest's install (`bundled`); one published as an archive is
downloaded there, checked against its pinned checksum (`download`); one Nest does not
fetch runs from the user's own install of it (`user_install`). A fetched npm engine's
version here is the one the base environment runs; a prepared environment
(`nestd/updates`) names newer ones in its manifest, applied below. A downloaded engine
moves with Nest's releases.

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

from pydantic import JsonValue

from nestd.updates.manifest import read_manifest

type Delivery = Literal["bundled", "download", "user_install"]
type SignIn = Literal["api_key", "terminal"]

# The MCP client's own default for one request, where an engine sets none.
MCP_DEFAULT_TIMEOUT = timedelta(minutes=1)
# Past the week a question waits (as Claude's do), so the question gives up first.
OPENCODE_MCP_TIMEOUT = timedelta(days=7, hours=1)


@dataclass(frozen=True)
class Download:
    """One platform's archive of an engine Nest downloads, as the ACP Registry lists it."""

    url: str
    sha256: str
    # The program inside the archive.
    program: str
    # What the registry adds to the engine's arguments on this platform.
    args: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcpEngine:
    id: str
    name: str
    # npm package and the pinned version; the package is None for one not on npm, and the
    # version for one Nest does not fetch.
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
    # Arguments added while agents may not push (`SessionSpec.guard_git`), and while
    # worktrees may not be removed (`guard_worktrees`, Autopilot): the engine's own denials.
    push_deny_args: tuple[str, ...] = ()
    worktree_deny_args: tuple[str, ...] = ()
    # The command that signs in, in Terminal: for `sign_in == "terminal"`, unless Nest signs
    # in itself with `login_method`.
    login_command: str | None = None
    # The ACP sign-in method `nestd engines sign-in` asks the engine for, for an engine
    # with no login command of its own.
    login_method: str | None = None
    # The engine's own login file, relative to the folder `auth_root` names (a variable,
    # else a folder in the home): signed in while it holds an entry. For an engine that
    # answers ACP signed out, so the probe cannot tell, or whose probe could sign it in.
    auth_file: str | None = None
    auth_root: tuple[str, str] = ("XDG_DATA_HOME", ".local/share")
    # Added to the probe's environment only.
    probe_env: Mapping[str, str] = field(default_factory=dict[str, str])
    # The variables that point the engine at an added account's own folder, by the
    # subfolder of the account folder they name ("" for the folder itself).
    home_env: Mapping[str, str] = field(default_factory=dict[str, str])
    # Where the engine is when the user installed it themselves (`user_install`).
    user_paths: tuple[str, ...] = ()
    # How long the engine waits for one call of an MCP tool, Nest's included.
    mcp_tool_timeout: timedelta = MCP_DEFAULT_TIMEOUT
    # What the engine is told in `_meta` when a session opens (`acp_meta`).
    session_meta: Mapping[str, JsonValue] = field(default_factory=dict[str, JsonValue])
    # The mode a session runs in outside plan mode, set again on every reopened session;
    # None keeps the session's own.
    normal_mode: str | None = None
    # Its entry in the ACP Registry (`engine/acp_registry.py`), where its pins come from.
    registry_id: str | None = None
    # A downloaded engine's archive by the registry's platform name (`download`).
    downloads: Mapping[str, Download] = field(default_factory=dict[str, Download])
    # Whether it asks before editing files inside its folder; one that does not cannot keep
    # a run to its write root (`SessionSpec.write_root`).
    asks_edits: bool = True

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
    registry_id="opencode",
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
    registry_id="gemini",
    home_env={"GEMINI_CLI_HOME": ""},
    mcp_tool_timeout=timedelta(minutes=10),
)
# Cursor asks before every command, MCP tool and fetch, its subagents' included, once its
# settings are Nest's (`engine/cursor_config.py`); a project's `.cursor/cli.json` could
# replace them, so Nest's runs read none. Its edits inside its folder are never asked
# (checked in its 2026.11.05 code, B153).
CURSOR = AcpEngine(
    id="cursor",
    name="Cursor agent",
    package=None,
    version=None,
    executable="agent",
    args=("--disable-project-configs", "acp"),
    delivery="user_install",
    sign_in="terminal",
    tested=False,
    git_guard=True,
    login_command="agent login",
    registry_id="cursor",
    user_paths=("~/.local/bin/agent",),
    asks_edits=False,
)
# Copilot asks before every command that is not read-only, every edit, fetch and MCP tool,
# its subagents' on the parent session (checked in 1.0.107, B153). The user's own saved
# approvals and its allow-all switches skip asking, but its `--deny-tool` rules win over
# all of them, so a guarded run gets them for pushes and pull requests. It reuses the
# user's `gh` login.
_COPILOT_PUSHES = tuple(
    f"--deny-tool=shell({command})"
    for command in (
        *("git push", "git send-pack", "git http-push"),
        *("gh pr", "gh api", "gh repo sync", "gh auth", "gh alias"),
    )
)
COPILOT = AcpEngine(
    id="copilot",
    name="Copilot CLI",
    package="@github/copilot",
    version="1.0.107",
    executable="copilot",
    args=("--acp", "--stdio", "--no-auto-update", "--disable-client-telemetry"),
    delivery="bundled",
    sign_in="terminal",
    tested=False,
    git_guard=True,
    env={
        # Over the user's own, which would run everything unasked.
        "COPILOT_ALLOW_ALL": "false",
        "COPILOT_AUTO_UPDATE": "false",
        "COPILOT_TELEMETRY_DISABLED": "true",
    },
    push_deny_args=_COPILOT_PUSHES,
    # Its rules match a git command's first subcommand unless they end in `:*`.
    worktree_deny_args=("--deny-tool=shell(git worktree remove:*)",),
    login_command="copilot login",
    # Never its autopilot, which runs everything unasked.
    normal_mode="agent",
    registry_id="github-copilot-cli",
    # An added account needs its own `gh` login as well, else it falls back to the user's.
    home_env={"COPILOT_HOME": "", "GH_CONFIG_DIR": "gh"},
    # For an MCP server given over ACP, whatever the server says (checked in 1.0.107).
    mcp_tool_timeout=timedelta(minutes=3),
)
# Antigravity's ACP server, as the registry publishes it (Google's own, not the `agy` CLI,
# whose users' permission rules still apply over ACP). It asks before every command,
# edit, fetch and MCP tool whatever the user's settings say, and refuses reads and edits
# outside its folder (checked in 1.4.5, B153). A subagent it defines runs commands
# unasked, so its subagent and workflow tools are switched off; a reopened session keeps
# the mode it was saved in, so it is put back in `default`, never `auto_edit` or `yolo`.
_AGY = "https://dl.google.com/agy-extensions/releases/{os}/agy-acp-server-1.4.5-{platform}.zip"
_AGY_PROGRAM = "agy_acp_server.par"
ANTIGRAVITY = AcpEngine(
    id="antigravity",
    name="Antigravity",
    package=None,
    version="1.4.5",
    executable=_AGY_PROGRAM,
    args=(),
    delivery="download",
    sign_in="terminal",
    tested=False,
    git_guard=True,
    # Its login in a file, never the Keychain, which could ask again when a version moves.
    env={"AGY_ACP_FORCE_FILE_STORAGE": "1"},
    session_meta={"antigravity": {"disabledTools": ["invoke_subagent", "run_workflow"]}},
    normal_mode="default",
    # Google's own login: the server opens the browser and waits for it.
    login_method="oauth-personal",
    auth_file="antigravity-acp/acp_token.json",
    auth_root=("GEMINI_HOME", ".gemini"),
    # A session opened with a login it cannot refresh opens the browser itself: never from
    # a probe.
    probe_env={"BROWSER": "true"},
    mcp_tool_timeout=timedelta(minutes=3),
    registry_id="antigravity-acp",
    downloads={
        "darwin-aarch64": Download(
            _AGY.format(os="macos", platform="darwin-arm64"),
            "886fff7767d08994ca39eb02c3d01a7532c7325a94aa33aaf52d52068733284f",
            _AGY_PROGRAM,
        ),
        "darwin-x86_64": Download(
            _AGY.format(os="macos", platform="darwin-x86_64"),
            "b39f3573c03b9acb9df028853f647527f1f3133f32bd77e78b796e48a205114a",
            _AGY_PROGRAM,
        ),
        "linux-x86_64": Download(
            _AGY.format(os="linux", platform="linux-x86_64"),
            "923923a0d7dc8073f66cc6f78647a3107e3a7ee2b7e1a24df8b3927b5188013b",
            _AGY_PROGRAM,
            ("--uid=",),
        ),
        "linux-aarch64": Download(
            _AGY.format(os="linux", platform="linux-arm64"),
            "7d64246633ae094f67e3bbcd2d679e89048f91346d5339313336e7483f40f056",
            _AGY_PROGRAM,
            ("--uid=",),
        ),
    },
)
# Grok Build runs a call unasked where the user's own rules or grants allow it, so Nest's
# git guard is its own answer to Grok's hook before every call (`acp_grok`); its other
# requests are judged as any engine's (checked in 1.0.79 against a local model, B153).
# It runs from its native program, never the npm launcher, which copies itself into the
# user's home and updates itself there.
GROK = AcpEngine(
    id="grok",
    name="Grok Build",
    package="@xai-official/grok",
    version="1.0.79",
    executable="grok",
    args=("agent", "--no-leader", "stdio"),
    delivery="bundled",
    sign_in="terminal",
    tested=False,
    git_guard=True,
    env={
        "GROK_DISABLE_AUTOUPDATER": "1",
        "DISABLE_TELEMETRY": "1",
        "GROK_TELEMETRY_ENABLED": "false",
        "GROK_TELEMETRY_TRACE_UPLOAD": "false",
        "DISABLE_ERROR_REPORTING": "1",
        # The user's Claude Code hooks are Claude's own.
        "GROK_CLAUDE_HOOKS_ENABLED": "false",
        # Else a folder it was never told to trust gets none of the project's instructions.
        "GROK_FOLDER_TRUST": "0",
    },
    login_command="grok login",
    auth_file="auth.json",
    auth_root=("GROK_HOME", ".grok"),
    registry_id="grok-build",
    home_env={"GROK_HOME": ""},
)
# As the base environment runs them.
BASE_ENGINES: tuple[AcpEngine, ...] = (OPENCODE, GEMINI, CURSOR, COPILOT, ANTIGRAVITY, GROK)


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
