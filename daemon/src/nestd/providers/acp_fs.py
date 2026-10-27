"""The file reads and writes an ACP engine asks Nest to do (B107).

Nest tells the engine it can read and write text files (`fs` client capabilities), so an
engine may send them to Nest instead of touching the disk itself: Gemini does for files in
its workspace, OpenCode writes an approved edit through Nest. A read is served only inside
the chat's folders; a write in a run with a write root (a pixie's, D072) only inside it.
Any other write was asked about first (`acp_permissions`).
"""

import asyncio
from collections.abc import Callable
from pathlib import Path

from pydantic import JsonValue

from nestd.providers.acp_permissions import AcpRules, within
from nestd.providers.acp_rpc import INVALID_PARAMS, RESOURCE_NOT_FOUND, AcpRpcError, JsonObject
from nestd.providers.codex_items import text

OUTSIDE_FOLDERS = "Nest reads files only in the chat's folders."
OUTSIDE_ROOT = "Nest refused the write: it is outside the folder this run may write in."
NOT_ABSOLUTE = "The path must be absolute."


class AcpFiles:
    def __init__(self, rules: Callable[[], AcpRules]) -> None:
        self._rules = rules

    async def read(self, params: JsonObject) -> JsonValue:
        path = _path(params)
        rules = self._rules()
        if not within([str(path)], rules.folders):
            raise AcpRpcError(INVALID_PARAMS, OUTSIDE_FOLDERS)
        try:
            content = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        except FileNotFoundError as error:
            raise AcpRpcError(RESOURCE_NOT_FOUND, f"No file {path}") from error
        except OSError as error:
            raise AcpRpcError(INVALID_PARAMS, f"{path} cannot be read") from error
        return {"content": _lines(content, params.get("line"), params.get("limit"))}

    async def write(self, params: JsonObject) -> JsonValue:
        path = _path(params)
        root = self._rules().write_root
        if root is not None and not within([str(path)], (root,)):
            raise AcpRpcError(INVALID_PARAMS, OUTSIDE_ROOT)
        content = text(params.get("content"))
        try:
            await asyncio.to_thread(_write, path, content)
        except OSError as error:
            raise AcpRpcError(INVALID_PARAMS, f"{path} cannot be written") from error
        return None


def _path(params: JsonObject) -> Path:
    path = Path(text(params.get("path")))
    if not path.is_absolute():
        raise AcpRpcError(INVALID_PARAMS, NOT_ABSOLUTE)
    return path


def _lines(content: str, line: JsonValue, limit: JsonValue) -> str:
    """`limit` lines from the 1-based `line`; the whole text when neither is given."""
    if not isinstance(line, int) and not isinstance(limit, int):
        return content
    lines = content.splitlines(keepends=True)
    start = max(0, line - 1) if isinstance(line, int) else 0
    end = start + max(0, limit) if isinstance(limit, int) else len(lines)
    return "".join(lines[start:end])


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
