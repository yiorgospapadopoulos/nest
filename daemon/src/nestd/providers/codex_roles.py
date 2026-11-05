"""The pixies a Codex run calls as Codex's own subagents, as agent roles (B112).

Each pixie is a role of the run's thread only: `agents.<slug>.description` and
`agents.<slug>.config_file` in the thread's config overrides, never in the user's
`config.toml`, with Codex's multi-agent feature switched on for the thread. A role's file
is a config layer for the subagent's thread: its developer instructions are the prompt the
pixie gets as a Claude subagent (call preamble, soul, memory to read, a leader's team), its
model and reasoning effort, its skill list (`skills.config`, as for a pixie's own chat),
and the run's own pixie tools switched off, which are only for the pixie whose run it is
(B41). The files live in a folder of the run's own, removed when it closes.

A called pixie works in its own mode, as a Claude subagent does. Nest decides the
subagent's approvals with that mode (`CodexRun.permissions`); a role names Codex's
approval policy, reviewer and sandbox only when its mode needs other ones than its
caller's run has, so its requests come to Nest (a read-only pixie's file changes always
do, to be declined).
"""

import json
import shutil
import tempfile
from collections.abc import Iterable, Mapping
from dataclasses import replace
from pathlib import Path

from pydantic import JsonValue

from nestd.config.models import PermissionMode
from nestd.providers.base import Subagent
from nestd.providers.codex_modes import CodexPermissions, codex_permissions
from nestd.providers.codex_rpc import JsonObject

# What Codex accepts as a role's or an MCP server's name in a dotted config key.
ROLE_NAME = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")
# Codex's cap of agents at once in a thread with pixie roles (B112).
MAX_AGENTS = 64
# The permission rule Nest gives a read-only pixie (`pixies.agents.EDIT_TOOLS`).
EDIT_TOOL = "Edit"


def read_only(subagent: Subagent) -> bool:
    return EDIT_TOOL in subagent.disallowed_tools


def skill_overrides(allowed: Iterable[str], skills: Iterable[tuple[str, bool]]) -> list[JsonValue]:
    """`skills.config` entries that leave only `allowed` of the folder's `skills` (by name,
    with whether the user's setup enables it): every other one is switched off, and one the
    user switched off stays off.
    """
    keep = set(allowed)
    return [
        {"name": name, "enabled": False}
        for name, enabled in sorted(set(skills))
        if name not in keep or not enabled
    ]


class CodexRoles:
    def __init__(
        self,
        subagents: Mapping[str, Subagent],
        guarded: bool,
        write_root: Path | None,
        skills: Iterable[tuple[str, bool]] = (),
        own_servers: JsonObject | None = None,
    ) -> None:
        """`skills` are the folder's skills, by name with whether they are on; `own_servers`
        the run's own tool servers (as thread config entries), off in every role.
        """
        self._subagents = {
            slug: subagent for slug, subagent in subagents.items() if set(slug) <= ROLE_NAME
        }
        self._guarded = guarded
        self._write_root = write_root
        self._skills = tuple(skills)
        self._own_servers = own_servers or {}
        self._folder = Path(tempfile.mkdtemp(prefix="nest-codex-roles-"))

    @property
    def folder(self) -> Path:
        return self._folder

    def config(self, mode: PermissionMode | None) -> JsonObject:
        """The thread's config overrides that offer the roles, with their files written
        for a caller in `mode`.
        """
        if not self._subagents:
            return {}
        self.write(mode)
        # No limit on pixies called at once (user, 2026-10-21), as on Claude: Codex's own
        # cap of agents at once is raised for the thread.
        config: JsonObject = {"features.multi_agent": True, "agents.max_threads": MAX_AGENTS}
        for slug, subagent in self._subagents.items():
            config[f"agents.{slug}.description"] = subagent.description
            config[f"agents.{slug}.config_file"] = str(self._path(slug))
        return config

    def write(self, mode: PermissionMode | None) -> None:
        """Write (again, when the caller's mode changed) every role's file."""
        caller = codex_permissions(mode, self._guarded, self._write_root)
        for slug, subagent in self._subagents.items():
            path = self._path(slug)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(self._role(subagent, mode, caller), encoding="utf-8")
            temporary.replace(path)

    def close(self) -> None:
        shutil.rmtree(self._folder, ignore_errors=True)

    def _path(self, slug: str) -> Path:
        return self._folder / f"{slug}.toml"

    def _role(
        self, subagent: Subagent, mode: PermissionMode | None, caller: CodexPermissions
    ) -> str:
        lines = [f"developer_instructions = {_string(subagent.prompt)}"]
        if subagent.model:
            lines.append(f"model = {_string(subagent.model)}")
        if subagent.effort:
            lines.append(f"model_reasoning_effort = {_string(subagent.effort)}")
        # Guarded in any chat, so a pixie's commands reach Nest, which declines pushes (B127).
        own = codex_permissions(subagent.permission_mode, True, self._write_root)
        if read_only(subagent) and own.approval_policy != "untrusted":
            own = replace(own, approval_policy="untrusted", reviewer="user")
        if own != caller:
            lines += [
                f"approval_policy = {_string(own.approval_policy)}",
                f"approvals_reviewer = {_string(own.reviewer)}",
                f"sandbox_mode = {_string(own.sandbox)}",
            ]
        for entry in skill_overrides(subagent.skills, self._skills) if subagent.skills else ():
            lines += ["", "[[skills.config]]", *_pairs(entry)]
        for key, server in self._own_servers.items():
            lines += ["", f"[{key}]", *_pairs({**_dict(server), "enabled": False})]
        return "\n".join(lines) + "\n"


def _pairs(table: JsonValue) -> list[str]:
    return [f"{key} = {_value(value)}" for key, value in _dict(table).items()]


def _dict(value: JsonValue) -> dict[str, JsonValue]:
    return value if isinstance(value, dict) else {}  # pyright: ignore[reportUnknownVariableType]


def _value(value: JsonValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return _string(str(value))


def _string(value: str) -> str:
    """A TOML basic string: JSON's escapes are TOML's."""
    return json.dumps(value, ensure_ascii=False)
