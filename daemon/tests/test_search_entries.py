from pydantic import JsonValue

from nestd.events import types
from nestd.search.entries import MAX_RESULT, MAX_TEXT, Entry, entries


def message(*blocks: JsonValue, parent: str | None = None) -> dict[str, JsonValue]:
    return {"blocks": list(blocks), "parent_tool_use_id": parent}


def test_a_user_message_is_indexed_by_its_text() -> None:
    assert entries(types.SESSION_USER_MESSAGE, {"text": "Fix the login", "attachments": []}) == [
        Entry("user", "Fix the login")
    ]


def test_assistant_text_tool_calls_and_results_are_indexed_thinking_is_not() -> None:
    payload = message(
        {"type": "thinking", "text": "secret musing"},
        {"type": "text", "text": "Looking at it."},
        {"type": "text", "text": "Found it."},
        {"type": "tool_use", "id": "t1", "name": "Bash", "input": {"command": "pytest -q\nls"}},
        {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/r/app.py"}},
        {"type": "tool_result", "tool_use_id": "t1", "content": "3   passed\n\nok"},
    )

    assert entries(types.SESSION_MESSAGE, payload) == [
        Entry("assistant", "Looking at it.\nFound it."),
        Entry("tool", "Bash pytest -q\nRead /r/app.py"),
        Entry("tool_result", "3 passed ok"),
    ]


def test_tool_calls_without_a_known_argument_keep_their_name() -> None:
    payload = message({"type": "tool_use", "id": "t", "name": "TodoWrite", "input": {"todos": []}})

    assert entries(types.SESSION_MESSAGE, payload) == [Entry("tool", "TodoWrite")]


def test_long_texts_are_cut() -> None:
    payload = message(
        {"type": "text", "text": "a" * (MAX_TEXT + 10)},
        {"type": "tool_result", "tool_use_id": "t", "content": "b " * MAX_RESULT, "is_error": True},
    )

    assistant, result = entries(types.SESSION_MESSAGE, payload)
    assert len(assistant.text) == MAX_TEXT
    assert len(result.text) == MAX_RESULT


def test_subagent_messages_blank_text_and_odd_payloads_give_nothing() -> None:
    assert entries(types.SESSION_MESSAGE, message({"type": "text", "text": "x"}, parent="t")) == []
    assert entries(types.SESSION_MESSAGE, message({"type": "text", "text": "  "})) == []
    assert entries(types.SESSION_MESSAGE, {"blocks": "nope"}) == []
    assert entries(types.SESSION_MESSAGE, message("text", {"type": "text", "text": 3})) == []
    assert entries(types.SESSION_USER_MESSAGE, {"text": None}) == []
    assert entries(types.SESSION_STATE, {"state": "idle"}) == []
