"""Anthropic Messages to Chat Completions and back."""

import json

from nestd.local.translate.anthropic_native import UsageFix, fixed_reply, native_request
from nestd.local.translate.anthropic_reply import AnthropicReply
from nestd.local.translate.anthropic_request import chat_request
from nestd.local.translate.values import JsonObject
from tests.test_local_translate_stream import call, counter, delta


def test_a_plain_request_keeps_model_limits_and_asks_for_usage() -> None:
    body: JsonObject = {
        "model": "qwen3-coder",
        "max_tokens": 32000,
        "temperature": 0.2,
        "top_p": 0.9,
        "stop_sequences": ["END"],
        "stream": True,
        "system": "Be brief.",
        "messages": [{"role": "user", "content": "hi"}],
        "thinking": {"type": "adaptive"},
        "context_management": {"edits": []},
        "output_config": {"effort": "high"},
        "metadata": {"user_id": "u"},
    }
    assert chat_request(body) == {
        "model": "qwen3-coder",
        "messages": [{"role": "system", "content": "Be brief."}, {"role": "user", "content": "hi"}],
        "max_tokens": 32000,
        "temperature": 0.2,
        "top_p": 0.9,
        "stop": ["END"],
        "stream": True,
        "stream_options": {"include_usage": True},
    }


def test_a_non_streaming_request_has_no_stream_options() -> None:
    assert chat_request({"model": "m", "messages": []}) == {
        "model": "m",
        "messages": [],
        "stream": False,
    }


def test_system_blocks_are_joined_and_cache_control_is_dropped() -> None:
    body: JsonObject = {
        "model": "m",
        "system": [
            {"type": "text", "text": "One.", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Two."},
        ],
        "messages": [],
    }
    assert chat_request(body)["messages"] == [{"role": "system", "content": "One.\n\nTwo."}]


def test_an_empty_system_is_left_out() -> None:
    assert chat_request({"model": "m", "system": [], "messages": []})["messages"] == []


def test_user_text_blocks_collapse_to_one_string() -> None:
    body: JsonObject = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "<system-reminder>x</system-reminder>"},
                    {"type": "text", "text": "Do it", "cache_control": {"type": "ephemeral"}},
                ],
            }
        ],
    }
    assert chat_request(body)["messages"] == [
        {"role": "user", "content": "<system-reminder>x</system-reminder>\n\nDo it"}
    ]


def test_images_become_data_urls_or_plain_urls() -> None:
    body: JsonObject = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/png", "data": "AAA"},
                    },
                    {"type": "image", "source": {"type": "url", "url": "https://x/y.png"}},
                    {"type": "image", "source": {"type": "file", "file_id": "f"}},
                    {"type": "document", "source": {}},
                ],
            }
        ],
    }
    assert chat_request(body)["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "What is this?"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
                {"type": "image_url", "image_url": {"url": "https://x/y.png"}},
            ],
        }
    ]


def test_tool_use_and_tool_result_round_trip() -> None:
    body: JsonObject = {
        "model": "m",
        "messages": [
            {"role": "user", "content": "Write a file"},
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "plan", "signature": "s"},
                    {"type": "text", "text": "Writing."},
                    {"type": "tool_use", "id": "toolu_1", "name": "Write", "input": {"a": 1}},
                    {"type": "tool_use", "id": "toolu_2", "name": "Read", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "ok"},
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_2",
                        "is_error": True,
                        "content": [{"type": "text", "text": "missing"}],
                    },
                    {"type": "text", "text": "Now continue"},
                ],
            },
        ],
    }
    assert chat_request(body)["messages"] == [
        {"role": "user", "content": "Write a file"},
        {
            "role": "assistant",
            "content": "Writing.",
            "tool_calls": [
                {
                    "id": "toolu_1",
                    "type": "function",
                    "function": {"name": "Write", "arguments": '{"a": 1}'},
                },
                {
                    "id": "toolu_2",
                    "type": "function",
                    "function": {"name": "Read", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "toolu_1", "content": "ok"},
        {"role": "tool", "tool_call_id": "toolu_2", "content": "Error: missing"},
        {"role": "user", "content": "Now continue"},
    ]


def test_an_assistant_turn_of_only_tool_calls_has_no_content() -> None:
    body: JsonObject = {
        "model": "m",
        "messages": [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t", "name": "Bash", "input": {}}],
            }
        ],
    }
    assert chat_request(body)["messages"] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": "t", "type": "function", "function": {"name": "Bash", "arguments": "{}"}}
            ],
        }
    ]


def test_assistant_string_content_and_empty_turns() -> None:
    body: JsonObject = {
        "model": "m",
        "messages": [
            {"role": "assistant", "content": "Sure."},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "x"}]},
            {"role": "user", "content": []},
            {"role": "user", "content": ""},
            "junk",
        ],
    }
    assert chat_request(body)["messages"] == [{"role": "assistant", "content": "Sure."}]


def test_images_in_a_tool_result_follow_as_a_user_message() -> None:
    image: JsonObject = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/jpeg", "data": "BBB"},
    }
    body: JsonObject = {
        "model": "m",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t",
                        "content": [{"type": "text", "text": "Read the image"}, image],
                    },
                    {"type": "tool_result", "tool_use_id": "u", "content": [image]},
                    {"type": "tool_result", "tool_use_id": "v"},
                ],
            }
        ],
    }
    url = {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,BBB"}}
    assert chat_request(body)["messages"] == [
        {"role": "tool", "tool_call_id": "t", "content": "Read the image"},
        {"role": "tool", "tool_call_id": "u", "content": "(image below)"},
        {"role": "tool", "tool_call_id": "v", "content": ""},
        {"role": "user", "content": [url, url]},
    ]


def test_tools_become_functions_and_server_tools_are_dropped() -> None:
    body: JsonObject = {
        "model": "m",
        "messages": [],
        "tools": [
            {
                "name": "Write",
                "description": "Write a file",
                "input_schema": {"type": "object", "properties": {}},
                "cache_control": {"type": "ephemeral"},
            },
            {"name": "Plain", "input_schema": {"type": "object"}},
            {"type": "web_search_20250305", "name": "web_search"},
        ],
    }
    assert chat_request(body)["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "Write",
                "description": "Write a file",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {"name": "Plain", "description": "", "parameters": {"type": "object"}},
        },
    ]


def test_tool_choice_maps_each_kind() -> None:
    def choice(value: JsonObject) -> JsonObject:
        return chat_request({"model": "m", "messages": [], "tool_choice": value})

    assert choice({"type": "auto"})["tool_choice"] == "auto"
    assert choice({"type": "any"})["tool_choice"] == "required"
    assert choice({"type": "none"})["tool_choice"] == "none"
    assert choice({"type": "tool", "name": "Bash"})["tool_choice"] == {
        "type": "function",
        "function": {"name": "Bash"},
    }
    serial = choice({"type": "auto", "disable_parallel_tool_use": True})
    assert serial["parallel_tool_calls"] is False
    assert "tool_choice" not in choice({"type": "weird"})


def events(raw: bytes) -> list[tuple[str, JsonObject]]:
    found: list[tuple[str, JsonObject]] = []
    for frame in raw.decode().strip().split("\n\n"):
        name_line, data_line = frame.split("\n")
        found.append(
            (name_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))
        )
    return found


def names(raw: bytes) -> list[str]:
    return [name for name, _ in events(raw)]


def test_message_start_announces_the_message() -> None:
    reply = AnthropicReply("qwen", counter())
    assert events(reply.start()) == [
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "model": "qwen",
                    "content": [],
                    "stop_reason": None,
                    "stop_sequence": None,
                    "usage": {"input_tokens": 0, "output_tokens": 0},
                },
            },
        )
    ]


def test_a_text_reply_streams_as_one_text_block() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    out = reply.feed(delta({"content": "Hel"})) + reply.feed(delta({"content": "lo"}, "stop"))
    out += reply.feed({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 2}})
    out += reply.finish()
    assert events(out) == [
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"input_tokens": 12, "output_tokens": 2},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    ]
    assert reply.done


def test_text_then_two_tool_calls_make_three_blocks() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    out = reply.feed(delta({"content": "Let me look."}))
    out += reply.feed(delta({"tool_calls": [call(0, "call_a", "Read", '{"file_')]}))
    out += reply.feed(delta({"tool_calls": [call(0, arguments='path": "a"}')]}))
    out += reply.feed(delta({"tool_calls": [call(1, "call_b", "Bash", '{"command": "ls"}')]}))
    out += reply.feed(delta({}, "tool_calls"))
    out += reply.finish()
    found = events(out)
    assert [name for name, _ in found] == [
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]
    assert found[3][1] == {
        "type": "content_block_start",
        "index": 1,
        "content_block": {"type": "tool_use", "id": "call_a", "name": "Read", "input": {}},
    }
    assert found[5][1] == {
        "type": "content_block_delta",
        "index": 1,
        "delta": {"type": "input_json_delta", "partial_json": 'path": "a"}'},
    }
    assert found[7][1]["index"] == 2
    assert [data["index"] for _, data in found[8:10]] == [1, 2]
    assert found[10][1]["delta"] == {"stop_reason": "tool_use", "stop_sequence": None}
    assert reply.message()["content"] == [
        {"type": "text", "text": "Let me look."},
        {"type": "tool_use", "id": "call_a", "name": "Read", "input": {"file_path": "a"}},
        {"type": "tool_use", "id": "call_b", "name": "Bash", "input": {"command": "ls"}},
    ]


def test_text_after_a_tool_call_opens_a_new_text_block() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    out = reply.feed(delta({"tool_calls": [call(0, "a", "A", "{}")]}))
    out += reply.feed(delta({"content": "and"}))
    out += reply.feed(delta({"content": " more"}))
    found = events(out)
    assert found[2] == (
        "content_block_start",
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    )
    assert len(found) == 5


def test_a_tool_call_announced_as_stop_still_ends_as_tool_use() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    reply.feed(delta({"tool_calls": [call(0, "a", "A", "{}")]}, "stop"))
    reply.finish()
    assert reply.message()["stop_reason"] == "tool_use"


def test_length_stops_as_max_tokens() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    reply.feed(delta({"content": "trunc"}, "length"))
    out = reply.finish()
    assert events(out)[1][1]["delta"] == {"stop_reason": "max_tokens", "stop_sequence": None}


def test_an_empty_reply_finishes_with_no_blocks() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    assert names(reply.finish()) == ["message_delta", "message_stop"]
    assert reply.message()["content"] == []


def test_an_error_chunk_ends_the_stream_with_an_error_event() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    out = reply.feed({"error": {"message": "model crashed"}})
    assert events(out) == [
        ("error", {"type": "error", "error": {"type": "api_error", "message": "model crashed"}})
    ]
    assert reply.done
    assert reply.error == "model crashed"


def test_fail_reports_a_broken_stream() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    assert events(reply.fail("connection lost")) == [
        ("error", {"type": "error", "error": {"type": "api_error", "message": "connection lost"}})
    ]
    assert reply.done


def test_message_for_a_whole_reply_parses_arguments() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.start()
    reply.feed(delta({"tool_calls": [call(0, "a", "A", "not json"), call(1, "b", "B")]}))
    reply.feed({"choices": [], "usage": {"prompt_tokens": 9, "completion_tokens": 4}})
    reply.finish()
    assert reply.message() == {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "qwen",
        "content": [
            {"type": "tool_use", "id": "a", "name": "A", "input": {}},
            {"type": "tool_use", "id": "b", "name": "B", "input": {}},
        ],
        "stop_reason": "tool_use",
        "stop_sequence": None,
        "usage": {"input_tokens": 9, "output_tokens": 4},
    }


def test_arguments_that_are_json_but_not_an_object_become_empty_input() -> None:
    reply = AnthropicReply("qwen", counter())
    reply.feed(delta({"tool_calls": [call(0, "a", "A", "[1]")]}))
    reply.finish()
    assert reply.message()["content"] == [{"type": "tool_use", "id": "a", "name": "A", "input": {}}]


def test_native_request_turns_system_messages_into_user_ones_in_place() -> None:
    reminder: JsonObject = {"role": "system", "content": [{"type": "text", "text": "Note."}]}
    body: JsonObject = {
        "model": "m",
        "system": [{"type": "text", "text": "You are Claude Code."}],
        "stream": True,
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello."},
            {"role": "system", "content": "Model switched."},
            reminder,
            "junk",
        ],
    }
    assert native_request(body) == {
        "model": "m",
        "system": [{"type": "text", "text": "You are Claude Code."}],
        "stream": True,
        "messages": [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "Hello."},
            {"role": "user", "content": "Model switched."},
            {"role": "user", "content": [{"type": "text", "text": "Note."}]},
            "junk",
        ],
    }
    # The caller's body is left as it was.
    assert reminder["role"] == "system"


def test_native_request_without_messages_is_unchanged() -> None:
    assert native_request({"model": "m"}) == {"model": "m"}


def test_a_reply_counting_cache_reads_in_its_input_gets_them_taken_out() -> None:
    body = {
        "id": "msg_1",
        "content": [{"type": "text", "text": "Hi"}],
        "usage": {"input_tokens": 1678, "cache_read_input_tokens": 1536, "output_tokens": 5},
    }
    assert json.loads(fixed_reply(json.dumps(body).encode())) == {
        **body,
        "usage": {"input_tokens": 142, "cache_read_input_tokens": 1536, "output_tokens": 5},
    }


def test_input_tokens_never_go_below_zero() -> None:
    body = {"usage": {"input_tokens": 10, "cache_read_input_tokens": 50}}
    assert json.loads(fixed_reply(json.dumps(body).encode()))["usage"]["input_tokens"] == 0


def test_replies_without_cache_reads_or_usage_stay_byte_for_byte() -> None:
    for raw in (
        b'{"usage": {"input_tokens": 1678, "cache_read_input_tokens": 0}}',
        b'{"usage": {"cache_read_input_tokens": 9, "output_tokens": 1}}',
        b'{"usage": {"input_tokens": 5}}',
        b'{"id": "msg_1"}',
        b'{"usage": null}',
        b"[1, 2]",
        b"not json",
    ):
        assert fixed_reply(raw) == raw


def native_event(kind: str, data: JsonObject) -> bytes:
    return f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode()


START = native_event(
    "message_start",
    {
        "type": "message_start",
        "message": {
            "id": "msg_1",
            "usage": {"input_tokens": 1678, "cache_read_input_tokens": 1536, "output_tokens": 0},
        },
    },
)
TEXT = native_event(
    "content_block_delta",
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
)
DELTA = native_event(
    "message_delta",
    {
        "type": "message_delta",
        "delta": {"stop_reason": "end_turn"},
        "usage": {"input_tokens": 1678, "cache_read_input_tokens": 1536, "output_tokens": 7},
    },
)
STOP = native_event("message_stop", {"type": "message_stop"})


def test_stream_usage_is_fixed_in_message_start_and_message_delta_only() -> None:
    fix = UsageFix()
    raw = START + TEXT + DELTA + STOP
    # Pieces that cut events anywhere, as the network does.
    out = b"".join(fix.feed(raw[i : i + 7]) for i in range(0, len(raw), 7)) + fix.finish()
    frames = out.split(b"\n\n")
    assert frames[-1] == b""
    assert [frame.split(b"\n")[0] for frame in frames[:-1]] == [
        b"event: message_start",
        b"event: content_block_delta",
        b"event: message_delta",
        b"event: message_stop",
    ]
    start = json.loads(frames[0].split(b"\n")[1].removeprefix(b"data: "))
    delta = json.loads(frames[2].split(b"\n")[1].removeprefix(b"data: "))
    assert start["message"]["usage"] == {
        "input_tokens": 142,
        "cache_read_input_tokens": 1536,
        "output_tokens": 0,
    }
    assert delta["usage"] == {
        "input_tokens": 142,
        "cache_read_input_tokens": 1536,
        "output_tokens": 7,
    }
    assert frames[1] + b"\n\n" == TEXT
    assert frames[3] + b"\n\n" == STOP


def test_each_event_is_forwarded_as_soon_as_it_is_whole() -> None:
    fix = UsageFix()
    assert fix.feed(TEXT[:10]) == b""
    assert fix.feed(TEXT[10:] + STOP[:5]) == TEXT
    assert fix.feed(STOP[5:]) == STOP
    assert fix.finish() == b""


def test_stream_events_without_cache_reads_stay_byte_for_byte() -> None:
    plain = native_event(
        "message_start",
        {"type": "message_start", "message": {"usage": {"input_tokens": 9, "output_tokens": 0}}},
    )
    odd = b": keep-alive\n\nevent: ping\ndata: not json\n\n"
    fix = UsageFix()
    assert fix.feed(plain + odd) + fix.finish() == plain + odd


def test_crlf_framed_events_are_fixed_too() -> None:
    fix = UsageFix()
    out = fix.feed(START.replace(b"\n", b"\r\n")) + fix.finish()
    assert out.startswith(b"event: message_start\r\n")
    assert out.endswith(b"\r\n\r\n")
    data = out.split(b"\r\n")[1].removeprefix(b"data: ")
    assert json.loads(data)["message"]["usage"]["input_tokens"] == 142


def test_an_unfinished_last_event_is_passed_on_at_the_end() -> None:
    fix = UsageFix()
    assert fix.feed(b"event: message_stop\ndata: {}") == b""
    assert fix.finish() == b"event: message_stop\ndata: {}"
