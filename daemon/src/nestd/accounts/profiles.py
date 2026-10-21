"""Profile folders of the accounts added in Nest (B98).

The first account of each engine is the user's own login: `~/.claude` and `~/.claude.json`,
and `~/.codex`, run exactly as without Nest. Every other account is a folder Nest owns,
`<data_dir>/profiles/<engine>/<id>/`, that the engine is pointed at with CLAUDE_CONFIG_DIR
or CODEX_HOME. Its path never changes: Claude Code names the account's Keychain item after
it. Everything but the login is shared with the first account by links, so agents behave
the same on every account; Claude's user MCP servers live beside the login in its
`.claude.json`, so they are copied in instead.

Nothing here ever writes, moves or deletes inside the first account's folders: only a
checked path inside the profiles folder is created or removed.
"""

import json
import logging
import re
import shutil
from collections.abc import Callable, MutableMapping
from dataclasses import dataclass
from pathlib import Path

from pydantic import JsonValue

from nestd.configuration.files import read_text, write_text
from nestd.errors import ConflictError

logger = logging.getLogger(__name__)

CLAUDE = "claude"
CODEX = "codex"
PROVIDERS = (CLAUDE, CODEX)
CLAUDE_CONFIG_DIR = "CLAUDE_CONFIG_DIR"
CODEX_HOME = "CODEX_HOME"
CODEX_SQLITE_HOME = "CODEX_SQLITE_HOME"
# A profile account's id, which is also its folder's name.
ACCOUNT_ID = re.compile(r"[0-9a-f]{12}")
# The account's own entries, never linked: Claude's login and its account file, Codex's
# login, its install id, scratch folders and SQLite state (shared by CODEX_SQLITE_HOME).
CLAUDE_OWN = frozenset({".credentials.json", ".claude.json", "backups"})
CODEX_OWN = frozenset({"auth.json", "installation_id", "tmp", ".tmp"})
CODEX_OWN_SUFFIXES = (".sqlite", ".sqlite-wal", ".sqlite-shm", ".sqlite-maintenance.lock")
ACCOUNT_FILE = ".claude.json"
# Where in `.claude.json` Claude Code keeps MCP servers: at the top, and for each project.
MCP_KEY = "mcpServers"
PROJECT_MCP_KEYS = (
    "mcpServers",
    "enabledMcpjsonServers",
    "disabledMcpjsonServers",
    "disabledMcpServers",
)
# Set in shells Claude Code runs; inherited, they make a profile show another account.
LEAKED_ENV = (
    "CLAUDE_CODE_USER_EMAIL",
    "CLAUDE_CODE_ACCOUNT_UUID",
    "CLAUDE_CODE_ORGANIZATION_UUID",
)

type JsonObject = dict[str, JsonValue]


class ProfileError(ConflictError):
    """A profile folder was refused or could not be made; nothing was changed."""


@dataclass(frozen=True)
class FirstAccount:
    """The user's own login folders; None where Nest was started without one (tests)."""

    claude_dir: Path | None
    claude_account_file: Path | None
    codex_home: Path | None


def drop_leaked_env(env: MutableMapping[str, str]) -> None:
    for name in LEAKED_ENV:
        env.pop(name, None)


class Profiles:
    def __init__(self, root: Path, first: FirstAccount) -> None:
        self.root = root
        self._first = first

    def folder(self, provider: str, account_id: str) -> Path:
        """The folder of a new profile account; refused unless the id is one Nest makes."""
        if provider not in PROVIDERS or not ACCOUNT_ID.fullmatch(account_id):
            msg = f"not a profile account: {provider} {account_id!r}"
            raise ProfileError(msg)
        return self.root / provider / account_id

    def checked(self, path: Path) -> Path:
        """`path` when it is a profile folder inside the profiles folder, else refused: the
        only folders Nest ever creates, prepares or removes.
        """
        absolute = path.absolute()
        inside = (
            absolute.parent.parent == self.root.absolute()
            and absolute.parent.name in PROVIDERS
            and ACCOUNT_ID.fullmatch(absolute.name) is not None
            # No link along the way leads elsewhere.
            and path.resolve().parent.parent == self.root.resolve()
        )
        if not inside or path.is_symlink():
            msg = f"{path} is not a profile folder of Nest's"
            raise ProfileError(msg)
        return path

    def env(self, provider: str, profile: Path | None) -> dict[str, str]:
        """What points the engine at the account: nothing for the first account."""
        if profile is None:
            return {}
        folder = str(self.checked(profile))
        if provider == CLAUDE:
            return {CLAUDE_CONFIG_DIR: folder}
        return {CODEX_HOME: folder, CODEX_SQLITE_HOME: str(self._first_codex())}

    def prepare(self, provider: str, profile: Path) -> dict[str, str]:
        """Make the folder and share the first account's setup into it; cheap when done.
        Returns the account's environment.
        """
        folder = self.checked(profile)
        if provider == CLAUDE:
            source = self._first_claude()
            own: Callable[[str], bool] = CLAUDE_OWN.__contains__
        else:
            source = self._first_codex()
            own = _codex_own
        env = self.env(provider, folder)
        folder.mkdir(parents=True, exist_ok=True)
        _link(source, folder, own)
        if provider == CLAUDE and self._first.claude_account_file is not None:
            _mirror_servers(self._first.claude_account_file, folder / ACCOUNT_FILE)
        return env

    def remove(self, profile: Path) -> None:
        """Delete the profile folder; its links go, never what they point to."""
        folder = self.checked(profile)
        if folder.exists():
            shutil.rmtree(folder)

    def _first_claude(self) -> Path:
        if self._first.claude_dir is None:
            msg = "Claude Code's folder is not known, so no Claude account can be added"
            raise ProfileError(msg)
        return self._first.claude_dir

    def _first_codex(self) -> Path:
        if self._first.codex_home is None:
            msg = "Codex's home is not known, so no Codex account can be added"
            raise ProfileError(msg)
        return self._first.codex_home


def _codex_own(name: str) -> bool:
    return name in CODEX_OWN or name.endswith(CODEX_OWN_SUFFIXES)


def _link(source: Path, folder: Path, own: Callable[[str], bool]) -> None:
    """A link for each entry of `source` the folder lacks; what it has is never replaced."""
    if not source.is_dir():
        return
    for entry in sorted(source.iterdir()):
        target = folder / entry.name
        if own(entry.name) or target.is_symlink():
            continue
        if target.exists():
            logger.info("%s keeps its own %s instead of the shared one", folder, entry.name)
            continue
        target.symlink_to(entry)


def _mirror_servers(source_file: Path, target_file: Path) -> None:
    """The first account's MCP server entries in the profile's own `.claude.json`; every
    other key (its account, its project state) is kept. Left alone when either file
    cannot be read.
    """
    source, target = _object(source_file), _object(target_file)
    if source is None or target is None:
        return
    mirrored = dict(target)
    _copy(source, mirrored, (MCP_KEY,))
    source_projects = _as_object(source.get("projects"))
    projects = {path: dict(_as_object(entry)) for path, entry in _projects(target).items()}
    for path, entry in source_projects.items():
        projects.setdefault(path, {})
        _copy(_as_object(entry), projects[path], PROJECT_MCP_KEYS)
    for path in list(projects):
        if path not in source_projects:
            _copy({}, projects[path], PROJECT_MCP_KEYS)
    kept: JsonObject = {path: entry for path, entry in projects.items() if entry}
    if kept or "projects" in target:
        mirrored["projects"] = kept
    if mirrored != target:
        write_text(target_file, json.dumps(mirrored, indent=2))


def _copy(source: JsonObject, target: JsonObject, keys: tuple[str, ...]) -> None:
    for key in keys:
        if key in source:
            target[key] = source[key]
        else:
            target.pop(key, None)


def _projects(data: JsonObject) -> JsonObject:
    return _as_object(data.get("projects"))


def _as_object(value: JsonValue) -> JsonObject:
    return value if isinstance(value, dict) else {}


def _object(path: Path) -> JsonObject | None:
    """The file's object, {} when missing or not an object; None when it is not JSON."""
    try:
        data: JsonValue = json.loads(read_text(path) or "{}")
    except ValueError:
        return None
    return _as_object(data)
