import pytest
from pydantic import JsonValue

from nestd.providers.base import ToolResultBlock, ToolUseBlock
from nestd.providers.codex_items import (
    DECLINED,
    file_paths,
    shown_command,
    tool_results,
    tool_uses,
)
from nestd.providers.codex_rpc import JsonObject

DIFF = "--- a/app.py\n+++ b/app.py\n@@ -1,3 +1,3 @@\n keep\n-old line\n+new line\n tail\n"


def test_a_command_is_a_bash_call_with_its_output() -> None:
    started: JsonObject = {"type": "commandExecution", "id": "c1", "command": "npm test"}
    done: JsonObject = {
        **started,
        "status": "completed",
        "aggregatedOutput": "9 passed",
        "exitCode": 0,
    }

    assert tool_uses(started) == [ToolUseBlock(id="c1", name="Bash", input={"command": "npm test"})]
    assert tool_results(done) == [ToolResultBlock(tool_use_id="c1", content="9 passed")]


@pytest.mark.parametrize(
    ("command", "shown"),
    [
        # As Codex sent them in the live check (B91).
        ("/bin/zsh -lc ls", "ls"),
        ("/bin/zsh -lc \"sed -n '1,20p' notes.txt\"", "sed -n '1,20p' notes.txt"),
        ("bash -c 'git status && git diff'", "git status && git diff"),
        ("/bin/sh -c 'echo hi'", "echo hi"),
        # Anything else is shown as it is.
        ("npm test", "npm test"),
        ("/bin/zsh -lc", "/bin/zsh -lc"),
        ("/bin/zsh -x 'ls'", "/bin/zsh -x 'ls'"),
        ("/bin/zsh -lc ls extra", "/bin/zsh -lc ls extra"),
        ("python -c 'print(1)'", "python -c 'print(1)'"),
        ("/bin/zsh -lc 'unclosed", "/bin/zsh -lc 'unclosed"),
        ("", ""),
    ],
)
def test_a_shell_wrapper_shows_the_command_inside_it(command: str, shown: str) -> None:
    assert shown_command(command) == shown


def test_a_wrapped_command_is_a_bash_call_of_the_inner_command() -> None:
    started: JsonObject = {"type": "commandExecution", "id": "c1", "command": "/bin/zsh -lc ls"}

    assert tool_uses(started) == [ToolUseBlock(id="c1", name="Bash", input={"command": "ls"})]


def test_a_failed_or_declined_command_is_an_error() -> None:
    failed: JsonObject = {
        "type": "commandExecution",
        "id": "c1",
        "status": "completed",
        "exitCode": 1,
    }
    declined: JsonObject = {
        "type": "commandExecution",
        "id": "c2",
        "status": "declined",
        "exitCode": None,
    }

    assert tool_results(failed)[0].is_error
    assert tool_results(failed)[0].content == ""
    assert tool_results(declined) == [
        ToolResultBlock(tool_use_id="c2", content=DECLINED, is_error=True)
    ]


def test_an_updated_file_is_an_edit_with_both_sides_of_the_diff() -> None:
    item: JsonObject = {
        "type": "fileChange",
        "id": "f1",
        "changes": [
            {"path": "/r/app.py", "kind": {"type": "update", "move_path": None}, "diff": DIFF}
        ],
    }

    [use] = tool_uses(item)

    assert use.name == "Edit"
    assert use.input == {
        "file_path": "/r/app.py",
        "old_string": "keep\nold line\ntail",
        "new_string": "keep\nnew line\ntail",
        "diff": DIFF,
    }


def test_a_new_file_without_hunks_is_a_write_and_a_deleted_one_an_edit_to_nothing() -> None:
    item: JsonObject = {
        "type": "fileChange",
        "id": "f1",
        "changes": [
            {"path": "/r/new.py", "kind": {"type": "add"}, "diff": "print('hi')\n"},
            {"path": "/r/gone.py", "kind": {"type": "delete"}, "diff": "old\n"},
            {"path": "/r/hunked.py", "kind": {"type": "add"}, "diff": "@@ -0,0 +1 @@\n+x\n"},
        ],
    }

    uses = tool_uses(item)

    assert [(u.id, u.name) for u in uses] == [("f1", "Write"), ("f1:1", "Edit"), ("f1:2", "Edit")]
    assert uses[0].input == {"file_path": "/r/new.py", "content": "print('hi')\n"}
    assert (uses[1].input["old_string"], uses[1].input["new_string"]) == ("old\n", "")
    assert (uses[2].input["old_string"], uses[2].input["new_string"]) == ("", "x")
    assert file_paths(item) == ["/r/new.py", "/r/gone.py", "/r/hunked.py"]


def test_a_file_change_result_is_given_for_each_file() -> None:
    changes: list[JsonValue] = [{"path": "a", "kind": {"type": "add"}, "diff": ""}] * 2
    done: JsonObject = {"type": "fileChange", "id": "f1", "changes": changes, "status": "completed"}
    failed: JsonObject = {**done, "status": "failed"}
    declined: JsonObject = {**done, "status": "declined"}

    assert [(r.tool_use_id, r.content, r.is_error) for r in tool_results(done)] == [
        ("f1", "Done", False),
        ("f1:1", "Done", False),
    ]
    assert tool_results(failed)[0].content == "The change could not be applied."
    assert tool_results(failed)[0].is_error
    assert tool_results(declined)[0].content == DECLINED


def test_an_mcp_call_is_named_like_claude_codes_with_its_text_result() -> None:
    item: JsonObject = {
        "type": "mcpToolCall",
        "id": "m1",
        "server": "github",
        "tool": "get_issue",
        "arguments": {"number": 3},
        "status": "completed",
        "result": {"content": [{"type": "text", "text": "Issue 3"}, {"type": "image"}]},
        "error": None,
    }

    assert tool_uses(item) == [
        ToolUseBlock(id="m1", name="mcp__github__get_issue", input={"number": 3})
    ]
    assert tool_results(item) == [ToolResultBlock(tool_use_id="m1", content="Issue 3")]


def test_a_failed_mcp_call_shows_its_error() -> None:
    item: JsonObject = {
        "type": "mcpToolCall",
        "id": "m1",
        "error": {"message": "timeout"},
        "status": "failed",
    }
    plain_failure: JsonObject = {"type": "mcpToolCall", "id": "m2", "status": "failed"}

    assert tool_results(item) == [
        ToolResultBlock(tool_use_id="m1", content="timeout", is_error=True)
    ]
    assert tool_results(plain_failure)[0].content == "The tool call failed."


def test_odd_mcp_arguments_are_kept_under_one_key() -> None:
    listed: JsonObject = {
        "type": "mcpToolCall",
        "id": "m1",
        "server": "s",
        "tool": "t",
        "arguments": [1],
    }
    missing: JsonObject = {"type": "mcpToolCall", "id": "m2", "server": "s", "tool": "t"}

    assert tool_uses(listed)[0].input == {"arguments": [1]}
    assert tool_uses(missing)[0].input == {}


def test_a_dynamic_tool_call_is_named_by_its_namespace() -> None:
    item: JsonObject = {
        "type": "dynamicToolCall",
        "id": "d1",
        "namespace": "nest",
        "tool": "remember",
        "arguments": {},
        "success": True,
        "contentItems": [{"type": "inputText", "text": "Saved"}],
    }
    bare: JsonObject = {**item, "namespace": None, "success": False}

    assert tool_uses(item)[0].name == "nest__remember"
    assert tool_results(item) == [ToolResultBlock(tool_use_id="d1", content="Saved")]
    assert tool_uses(bare)[0].name == "remember"
    assert tool_results(bare)[0].is_error


def test_an_image_view_is_a_read() -> None:
    item: JsonObject = {"type": "imageView", "id": "i1", "path": "/r/shot.png"}

    assert tool_uses(item) == [
        ToolUseBlock(id="i1", name="Read", input={"file_path": "/r/shot.png"})
    ]
    assert tool_results(item)[0].content == "Viewed the image"


def test_web_searches_read_their_query_and_what_they_did() -> None:
    search: JsonObject = {
        "type": "webSearch",
        "id": "w1",
        "query": "codex",
        "action": None,
        "results": [1, 2],
    }
    queries: JsonObject = {
        "type": "webSearch",
        "id": "w2",
        "query": "",
        "action": {"type": "search", "queries": ["a", "b"]},
        "results": None,
    }
    page: JsonObject = {
        "type": "webSearch",
        "id": "w3",
        "query": "",
        "action": {"type": "open_page", "url": "https://x.dev"},
    }
    find: JsonObject = {
        "type": "webSearch",
        "id": "w4",
        "query": "",
        "action": {"type": "find_in_page", "url": "https://x.dev", "pattern": "api"},
    }

    assert tool_uses(search)[0].input == {"query": "codex"}
    assert tool_results(search)[0].content == "2 results"
    assert tool_uses(queries)[0].input == {"query": "a | b"}
    assert tool_results(queries)[0].content == "Searched"
    assert tool_uses(page)[0].input == {"query": "https://x.dev"}
    assert tool_results(page)[0].content == "Opened https://x.dev"
    assert tool_results(find)[0].content == "Searched the page for api"


def test_other_items_are_no_tool_calls() -> None:
    assert tool_uses({"type": "agentMessage", "id": "a"}) == []
    assert tool_results({"type": "plan", "id": "p"}) == []
