"""Cursor's settings for Nest's runs: the user's own, made to ask before every command (B153).

Cursor's agent decides by itself what runs without asking, from `approvalMode` and the
`permissions` allow list in its `cli-config.json`, and no flag or variable makes it ask
more (checked in its 2026.11.05 code). So Nest's runs read that file from a folder of
Nest's (`CURSOR_CONFIG_DIR`): a copy of the user's, remade at each launch, with
`approvalMode` set to the allow list, an empty allow list and web searches asked. The rest
of the user's settings (model, attribution, editor...) stay; their MCP servers, hooks and
skills are read from `~/.cursor` whatever the folder. Its sessions (`acp-sessions/`) stay
in Nest's folder, so a chat reopens them. The login stays in the Keychain.

Cursor writes the file back while it runs (the model it uses, its login details), so the
copy is replaced whole, never edited in place.
"""

import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import cast

CONFIG_FILE = "cli-config.json"
CONFIG_DIR_ENV = "CURSOR_CONFIG_DIR"
# Nest's rules over the user's: ask before everything Cursor would otherwise allow.
_ASK_ALWAYS: dict[str, object] = {
    "approvalMode": "allowlist",
    "permissions": {"allow": [], "deny": []},
    "autoAcceptWebSearch": False,
}
# Keys that would let a call through unasked.
_DROPPED = ("webFetchDomainAllowlist",)


def user_config_dir(env: Mapping[str, str], home: Path) -> Path:
    """Where the user's own Cursor reads its settings."""
    found = env.get(CONFIG_DIR_ENV)
    return Path(found) if found else home / ".cursor"


def nest_config(user: Mapping[str, object]) -> dict[str, object]:
    settings = {key: value for key, value in user.items() if key not in _DROPPED}
    return {**settings, **_ASK_ALWAYS}


def write_config(folder: Path, user_dir: Path) -> Path:
    """Nest's copy of the user's settings in `folder`, made now; returns `folder`."""
    folder.mkdir(parents=True, exist_ok=True)
    text = json.dumps(nest_config(_read(user_dir / CONFIG_FILE)), indent=2)
    handle, temporary = tempfile.mkstemp(dir=folder, prefix=f".{CONFIG_FILE}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as file:
            file.write(text)
        Path(temporary).replace(folder / CONFIG_FILE)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    # A permissions file there would hold allow rules of its own.
    (folder / "permissions.json").unlink(missing_ok=True)
    return folder


def _read(path: Path) -> dict[str, object]:
    """The user's settings; none when the file is missing or not an object."""
    try:
        found: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cast("dict[str, object]", found) if isinstance(found, dict) else {}
