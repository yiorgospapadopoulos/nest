"""What Nest sends in `_meta` when it opens a session, for the engines that take their
settings there (B153).

Each engine's fixed settings (`AcpEngine.session_meta`) and its launch's (`AcpLaunch.meta`,
which name Nest's folders) go with `session/new`, `session/load` and `session/resume`
alike, since a reopened session forgets them. Grok Build's are Nest's hook and, in a
guarded run, Nest's plugin (`acp_grok`).

Antigravity's ACP server reads no instruction file at all (checked in 1.4.5), so Nest
gives it the ones Antigravity's own apps read, as its system prompt's addition: the user's
`~/.gemini/GEMINI.md`, then the project's `AGENTS.md` and `GEMINI.md` when they are files
of the project's own, not links, each named as Claude Code names the files it loads.
"""

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from pydantic import JsonValue

from nestd.providers.acp_engines import ANTIGRAVITY, GROK, AcpEngine
from nestd.providers.acp_grok import hook_meta, plugin_dir
from nestd.providers.acp_process import AcpLaunch
from nestd.providers.acp_rpc import JsonObject

# The most of one instruction file Nest passes on.
INSTRUCTION_LIMIT = 100_000
_PROJECT_FILES = ("AGENTS.md", "GEMINI.md")


def session_meta(engine: AcpEngine, launch: AcpLaunch, cwd: Path, guarded: bool) -> JsonObject:
    """`guarded`: the run may not push (`SessionSpec.guard_git`)."""
    meta = merged(engine.session_meta, launch.meta)
    if engine.id == GROK.id:
        meta = merged(meta, hook_meta())
        if guarded:
            meta["pluginDirs"] = [str(plugin_dir())]
    if engine.id == ANTIGRAVITY.id:
        home = launch.env.get("HOME")
        text = instructions(cwd, Path(home) if home else None)
        if text:
            meta = merged(meta, {"antigravity": {"systemPrompt": {"append": text}}})
    return meta


def instructions(cwd: Path, home: Path | None) -> str:
    """The instruction files Antigravity's apps read, each with its path, in order. A
    project's must be a file of its own, never a link: one a repository makes to a file
    elsewhere (a key, say) would send that file to the model. The user's own may be one.
    """
    found = [] if home is None else [(home / ".gemini" / "GEMINI.md", True)]
    found += [(cwd / name, False) for name in _PROJECT_FILES]
    parts: list[str] = []
    for path, own in found:
        text = _read(path, follow=own)
        if text.strip():
            parts.append(f"Contents of {path}:\n\n{text.strip()}")
    return "\n\n".join(parts)


def _read(path: Path, *, follow: bool) -> str:
    """A regular file's start; nothing when it is missing, not a file, or a link Nest may
    not follow.
    """
    flags = os.O_RDONLY | (0 if follow else os.O_NOFOLLOW)
    try:
        handle = os.open(path, flags)
    except OSError:
        return ""
    with os.fdopen(handle, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            return ""
        return file.read(INSTRUCTION_LIMIT).decode("utf-8", errors="replace")


def merged(base: Mapping[str, JsonValue], over: Mapping[str, JsonValue]) -> JsonObject:
    """`over` on `base`, objects merged key by key at every depth."""
    result: JsonObject = dict(base)
    for key, value in over.items():
        current = result.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            result[key] = merged(
                cast("dict[str, JsonValue]", current), cast("dict[str, JsonValue]", value)
            )
        else:
            result[key] = value
    return result
