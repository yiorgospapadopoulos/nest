"""Codex's thread items as Nest's transcript blocks (B91, D113).

Tool items get the names Claude Code uses for the same work, so clients draw them as they
draw Claude's: a command is `Bash`, a file change `Edit` (or `Write` for a new file whose
diff holds no hunks), an MCP tool call `mcp__<server>__<tool>`, a web search `WebSearch`
and an image Codex looked at `Read`. A file change with several files is one call per file.
Codex runs each command through the user's shell (`/bin/zsh -lc '<command>'`); the call
shows the command inside it.
"""

import re
import shlex
from pathlib import PurePosixPath
from typing import cast

from pydantic import JsonValue

from nestd.providers.base import ToolResultBlock, ToolUseBlock
from nestd.providers.codex_rpc import JsonObject

# The kinds of item drawn as tool calls; a web search only once it is done, since its
# query is filled in then.
TOOL_ITEMS = frozenset(
    {"commandExecution", "fileChange", "mcpToolCall", "dynamicToolCall", "imageView"}
)
DECLINED = "The user declined this."
_FAILED = frozenset({"failed", "declined"})
_HUNK = re.compile(r"^@@.*@@", re.MULTILINE)
_SHELLS = frozenset({"zsh", "bash", "sh"})
_COMMAND_FLAGS = frozenset({"-c", "-lc"})


def text(value: JsonValue | None) -> str:
    return value if isinstance(value, str) else ""


def obj(value: JsonValue | None) -> JsonObject:
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def items(value: JsonValue | None) -> list[JsonValue]:
    return cast("list[JsonValue]", value) if isinstance(value, list) else []


def tool_uses(item: JsonObject) -> list[ToolUseBlock]:
    """The calls an item makes, when Codex starts it."""
    kind = item.get("type")
    item_id = text(item.get("id"))
    if kind == "commandExecution":
        command = shown_command(text(item.get("command")))
        return [ToolUseBlock(id=item_id, name="Bash", input={"command": command})]
    if kind == "fileChange":
        return [_file_use(item_id, index, obj(change)) for index, change in _changes(item)]
    if kind == "mcpToolCall":
        name = f"mcp__{text(item.get('server'))}__{text(item.get('tool'))}"
        return [ToolUseBlock(id=item_id, name=name, input=_arguments(item))]
    if kind == "dynamicToolCall":
        namespace = text(item.get("namespace"))
        tool = text(item.get("tool"))
        name = f"{namespace}__{tool}" if namespace else tool
        return [ToolUseBlock(id=item_id, name=name, input=_arguments(item))]
    if kind == "imageView":
        return [ToolUseBlock(id=item_id, name="Read", input={"file_path": text(item.get("path"))})]
    if kind == "webSearch":
        return [ToolUseBlock(id=item_id, name="WebSearch", input={"query": _query(item)})]
    return []


def tool_results(item: JsonObject) -> list[ToolResultBlock]:
    """What an item's calls returned, when Codex completes it."""
    kind = item.get("type")
    item_id = text(item.get("id"))
    status = text(item.get("status"))
    if kind == "commandExecution":
        exit_code = item.get("exitCode")
        failed = status in _FAILED or (isinstance(exit_code, int) and exit_code != 0)
        output = DECLINED if status == "declined" else text(item.get("aggregatedOutput"))
        return [ToolResultBlock(tool_use_id=item_id, content=output, is_error=failed)]
    if kind == "fileChange":
        content = "Done"
        if status == "declined":
            content = DECLINED
        elif status in _FAILED:
            content = "The change could not be applied."
        return [
            ToolResultBlock(
                tool_use_id=_file_id(item_id, index), content=content, is_error=status in _FAILED
            )
            for index, _ in _changes(item)
        ]
    if kind in ("mcpToolCall", "dynamicToolCall"):
        return [_call_result(item_id, item)]
    if kind == "imageView":
        return [ToolResultBlock(tool_use_id=item_id, content="Viewed the image")]
    if kind == "webSearch":
        return [ToolResultBlock(tool_use_id=item_id, content=_search_result(item))]
    return []


def shown_command(command: str) -> str:
    """The command inside a shell wrapper such as `/bin/zsh -lc 'ls'`; any other command
    as it is.
    """
    try:
        words = shlex.split(command)
    except ValueError:
        return command
    if len(words) == 3 and PurePosixPath(words[0]).name in _SHELLS and words[1] in _COMMAND_FLAGS:
        return words[2]
    return command


def file_paths(item: JsonObject) -> list[str]:
    return [text(obj(change).get("path")) for _, change in _changes(item)]


def _changes(item: JsonObject) -> list[tuple[int, JsonValue]]:
    return list(enumerate(items(item.get("changes"))))


def _file_id(item_id: str, index: int) -> str:
    return item_id if index == 0 else f"{item_id}:{index}"


def _file_use(item_id: str, index: int, change: JsonObject) -> ToolUseBlock:
    path = text(change.get("path"))
    diff = text(change.get("diff"))
    kind = text(obj(change.get("kind")).get("type"))
    tool_id = _file_id(item_id, index)
    if kind == "add" and not _HUNK.search(diff):
        return ToolUseBlock(id=tool_id, name="Write", input={"file_path": path, "content": diff})
    old, new = _sides(diff)
    if kind == "delete" and not _HUNK.search(diff):
        old, new = diff, ""
    return ToolUseBlock(
        id=tool_id,
        name="Edit",
        input={"file_path": path, "old_string": old, "new_string": new, "diff": diff},
    )


def _sides(diff: str) -> tuple[str, str]:
    """A unified diff's hunks as the text before and after, for an Edit's two strings."""
    old: list[str] = []
    new: list[str] = []
    in_hunk = False
    for line in diff.splitlines():
        if _HUNK.match(line):
            in_hunk = True
        elif in_hunk and line.startswith("-"):
            old.append(line[1:])
        elif in_hunk and line.startswith("+"):
            new.append(line[1:])
        elif in_hunk and line.startswith(" "):
            old.append(line[1:])
            new.append(line[1:])
    return "\n".join(old), "\n".join(new)


def _arguments(item: JsonObject) -> dict[str, JsonValue]:
    arguments = item.get("arguments")
    if isinstance(arguments, dict):
        return cast("dict[str, JsonValue]", arguments)
    return {} if arguments is None else {"arguments": arguments}


def _call_result(item_id: str, item: JsonObject) -> ToolResultBlock:
    error = obj(item.get("error"))
    if error or item.get("success") is False or text(item.get("status")) in _FAILED:
        message = text(error.get("message")) or "The tool call failed."
        return ToolResultBlock(tool_use_id=item_id, content=message, is_error=True)
    result = obj(item.get("result"))
    parts = items(result.get("content")) or items(item.get("contentItems"))
    texts = [text(obj(part).get("text")) for part in parts]
    return ToolResultBlock(tool_use_id=item_id, content="\n".join(t for t in texts if t))


def _query(item: JsonObject) -> str:
    action = obj(item.get("action"))
    queries = [text(q) for q in items(action.get("queries"))]
    return (
        text(item.get("query"))
        or text(action.get("query"))
        or " | ".join(q for q in queries if q)
        or text(action.get("url"))
    )


def _search_result(item: JsonObject) -> str:
    action = obj(item.get("action"))
    if action.get("type") == "open_page":
        return f"Opened {text(action.get('url'))}".strip()
    if action.get("type") == "find_in_page":
        return f"Searched the page for {text(action.get('pattern'))}".strip()
    results = items(item.get("results"))
    return f"{len(results)} results" if results else "Searched"
