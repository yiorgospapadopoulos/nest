import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest

from nestd.claude_sessions.transcript import parse_transcript, read_transcript
from nestd.events import types
from tests.claude_support import Entry, assistant, simple_chat, text, user


def jsonl(entries: Sequence[Entry], *extra_lines: str) -> str:
    return "\n".join([*(json.dumps({"cwd": "/r", **e}) for e in entries), *extra_lines])


def history(entries: Sequence[Entry]) -> list[tuple[str, object]]:
    transcript = parse_transcript(jsonl(entries))
    return [(item.type, item.payload) for item in transcript.history]


def message(*blocks: object) -> tuple[str, object]:
    return (types.SESSION_MESSAGE, {"blocks": list(blocks), "parent_tool_use_id": None})


def prompt(value: str) -> tuple[str, object]:
    return (types.SESSION_USER_MESSAGE, {"text": value, "attachments": []})


def test_a_simple_chat_becomes_session_events() -> None:
    transcript = parse_transcript(jsonl(simple_chat()))

    assert [(item.type, item.payload, item.ts) for item in transcript.history] == [
        (*prompt("Fix the login bug. It fails"), datetime(2026, 10, 5, 9, 0, tzinfo=UTC)),
        (
            *message({"type": "text", "text": "Fixed."}),
            datetime(2026, 10, 5, 9, 1, tzinfo=UTC),
        ),
    ]
    assert transcript.first_prompt == "Fix the login bug. It fails"
    assert transcript.title is None
    assert transcript.display_title == "Fix the login bug"
    assert transcript.cwd == Path("/r")
    assert transcript.created_at == datetime(2026, 10, 5, 9, 0, tzinfo=UTC)
    assert transcript.message_count == 2


@pytest.mark.parametrize(
    ("extra", "title"),
    [
        (
            [
                {"type": "custom-title", "customTitle": "First name"},
                {"type": "ai-title", "aiTitle": "Generated"},
                {"type": "custom-title", "customTitle": " Renamed "},
                {"type": "custom-title", "customTitle": "   "},
            ],
            "Renamed",
        ),
        ([{"type": "ai-title", "aiTitle": "Generated"}, {"type": "summary"}], "Generated"),
        (
            [{"type": "summary", "summary": "Old summary"}, {"type": "user", "summary": "no"}],
            "Old summary",
        ),
        ([{"type": "custom-title", "customTitle": 3}], None),
    ],
)
def test_titles_come_from_claude_code_first(extra: list[Entry], title: str | None) -> None:
    transcript = parse_transcript(jsonl([*simple_chat(), *extra]))

    assert transcript.title == title
    assert transcript.display_title == (title or "Fix the login bug")


def test_an_empty_transcript_has_no_title() -> None:
    transcript = parse_transcript(jsonl([{"type": "queue-operation"}], "not json", "[1, 2]", ""))

    assert transcript.history == []
    assert transcript.display_title is None
    assert transcript.first_prompt is None
    assert transcript.created_at is None


def test_internal_entries_and_text_are_skipped() -> None:
    entries = [
        user("u0", "<local-command-caveat>Caveat</local-command-caveat>"),
        user("u1", "Real prompt", "u0"),
        {"type": "attachment", "uuid": "t1", "parentUuid": "u1"},
        user("m1", "Meta context", "t1", isMeta=True),
        user("c1", "Summary of earlier", "m1", isCompactSummary=True),
        user("n1", "<task-notification>done</task-notification>", "c1"),
        user("r1", "[Request interrupted by user for tool use]", "n1"),
        user("s1", "<system-reminder>x</system-reminder>", "r1"),
        user("e1", "   ", "s1"),
        user("x1", [text("<bash-input>ls</bash-input>"), text("")], "e1"),
        {"type": "system", "uuid": "y1", "parentUuid": "x1", "subtype": "stop_hook_summary"},
        assistant("a1", [text("Answer")], "y1"),
        assistant("a2", [{"type": "mystery"}, {"type": "text"}], "a1"),
        {"type": "assistant", "uuid": "a3", "parentUuid": "a2", "message": {"content": "flat"}},
        {"type": "assistant", "uuid": "a4", "parentUuid": "a3", "message": "not a dict"},
        user("u2", "Next", "a4"),
    ]

    assert history(entries) == [
        prompt("Real prompt"),
        message({"type": "text", "text": "Answer"}),
        prompt("Next"),
    ]


def test_sidechain_messages_are_left_out() -> None:
    entries = [
        user("u1", "Main prompt"),
        assistant("s1", [text("Subagent")], "u1", isSidechain=True),
        assistant("a1", [text("Main reply")], "u1"),
    ]

    assert history(entries) == [
        prompt("Main prompt"),
        message({"type": "text", "text": "Main reply"}),
    ]


@pytest.mark.parametrize(
    ("content", "shown"),
    [
        ("<command-name>/review</command-name><command-args>PR 4</command-args>", "/review PR 4"),
        ("<command-message>clear</command-message><command-name>/clear</command-name>", "/clear"),
        ("<command-name> </command-name><command-args></command-args>", None),
    ],
)
def test_slash_commands_show_as_typed(content: str, shown: str | None) -> None:
    assert history([user("u1", content)]) == ([prompt(shown)] if shown else [])


def test_images_and_text_in_one_prompt() -> None:
    entries = [
        user(
            "u1", [text("Look at this"), {"type": "image", "source": {"type": "base64"}}, "stray"]
        ),
        user("u2", [{"type": "image", "source": {"type": "base64"}}], "u1"),
    ]

    assert history(entries) == [prompt("Look at this\n[image]"), prompt("[image]")]


def test_tools_thinking_and_results() -> None:
    entries = [
        user("u1", "Search it"),
        assistant(
            "a1",
            [
                {"type": "thinking", "thinking": "Hmm", "signature": "s"},
                {"type": "redacted_thinking", "data": "x"},
                {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a"}},
                {"type": "server_tool_use", "id": "t2", "name": "web_search", "input": {}},
                {"type": "tool_use", "id": "t3", "name": "Bad", "input": "not a dict"},
                {"type": "tool_use", "name": "NoId", "input": {}},
                {
                    "type": "web_search_tool_result",
                    "tool_use_id": "t2",
                    "content": [{"type": "web_search_result", "url": "https://x.dev"}],
                },
            ],
            "u1",
        ),
        user(
            "u2",
            [
                {"type": "tool_result", "tool_use_id": "t1", "content": "line"},
                {
                    "type": "tool_result",
                    "tool_use_id": "t4",
                    "content": [{"type": "text", "text": "a"}, {"type": "image"}, {"type": "text"}],
                    "is_error": True,
                },
                {"type": "tool_result", "tool_use_id": "t5"},
                {"type": "tool_result", "tool_use_id": "t6", "content": {"k": "v"}},
                {"type": "tool_result", "content": "no id"},
                text("And also"),
            ],
            "a1",
        ),
    ]

    assert history(entries) == [
        prompt("Search it"),
        message(
            # Claude Code's transcripts do not say how long the agent thought (D045).
            {"type": "thinking", "text": "Hmm", "duration_ms": None},
            {"type": "thinking", "text": "", "duration_ms": None},
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": "/a"}},
            {"type": "tool_use", "id": "t2", "name": "web_search", "input": {}},
            {
                "type": "tool_result",
                "tool_use_id": "t2",
                "content": "[web_search_result]",
                "is_error": False,
            },
        ),
        message(
            {"type": "tool_result", "tool_use_id": "t1", "content": "line", "is_error": False},
            {
                "type": "tool_result",
                "tool_use_id": "t4",
                "content": "a\n[image]\n",
                "is_error": True,
            },
            {"type": "tool_result", "tool_use_id": "t5", "content": "", "is_error": False},
            {
                "type": "tool_result",
                "tool_use_id": "t6",
                "content": '{"k": "v"}',
                "is_error": False,
            },
        ),
        prompt("And also"),
    ]
    assert parse_transcript(jsonl(entries)).message_count == 2


def test_a_rewound_branch_is_replaced_by_the_newer_one() -> None:
    entries = [
        user("u1", "Start"),
        assistant("a1", [text("Old answer")], "u1"),
        user("u2", "Old follow-up", "a1"),
        user("u3", "Edited follow-up", "a1"),
        assistant("a3", [text("New answer")], "u3"),
        {"type": "last-prompt", "lastPrompt": "Edited follow-up"},
    ]

    assert history(entries) == [
        prompt("Start"),
        message({"type": "text", "text": "Old answer"}),
        prompt("Edited follow-up"),
        message({"type": "text", "text": "New answer"}),
    ]


def test_history_before_a_compaction_is_kept() -> None:
    entries = [
        user("u1", "Before"),
        assistant("a1", [text("Early")], "u1"),
        {
            "type": "system",
            "subtype": "compact_boundary",
            "uuid": "b1",
            "parentUuid": None,
            "logicalParentUuid": "a1",
        },
        user("c1", "This session is being continued...", "b1", isCompactSummary=True),
        user("u2", "After", "c1"),
    ]

    assert history(entries) == [
        prompt("Before"),
        message({"type": "text", "text": "Early"}),
        prompt("After"),
    ]


def test_broken_links_end_the_history() -> None:
    cycle = [user("u1", "One", "u2"), user("u2", "Two", "u1")]
    missing = [user("u1", "Orphan", "gone")]

    assert history(cycle) == [prompt("One"), prompt("Two")]
    assert history(missing) == [prompt("Orphan")]


def test_times_are_read_leniently() -> None:
    entries = [
        {"type": "queue-operation", "timestamp": "yesterday"},
        user("u1", "First", timestamp="2026-10-05T10:00:00"),
        user("u2", "Second", "u1", timestamp=None),
    ]

    transcript = parse_transcript(jsonl(entries))

    assert transcript.created_at == datetime(2026, 10, 5, 10, 0, tzinfo=UTC)
    assert [item.ts for item in transcript.history] == [transcript.created_at, None]


def test_read_transcript_reads_the_file(tmp_path: Path) -> None:
    path = tmp_path / "chat.jsonl"
    path.write_text(jsonl(simple_chat()), encoding="utf-8")

    assert read_transcript(path).first_prompt == "Fix the login bug. It fails"
    with pytest.raises(OSError, match="No such file"):
        read_transcript(tmp_path / "missing.jsonl")


@pytest.mark.parametrize(
    ("entries", "entrypoint"),
    [
        (
            [
                {"type": "queue-operation", "entrypoint": 3},
                user("u1", "Review this change", entrypoint="sdk-py"),
                user("u2", "Later", "u1", entrypoint="cli"),
            ],
            "sdk-py",
        ),
        ([user("u1", "Hello", entrypoint="claude-desktop")], "claude-desktop"),
        (simple_chat(), None),
    ],
)
def test_the_entrypoint_is_the_first_one_recorded(
    entries: list[Entry], entrypoint: str | None
) -> None:
    assert parse_transcript(jsonl(entries)).entrypoint == entrypoint
