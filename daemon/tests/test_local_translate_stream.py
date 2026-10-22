"""The shared parts of the translator: reading upstream chat-completion chunks, SSE framing
and upstream error text."""

import json
from collections.abc import AsyncIterator

from pydantic import JsonValue

from nestd.local.translate.chat_stream import (
    ChunkDecoder,
    TextDelta,
    ToolArguments,
    ToolStart,
    Usage,
    completion_chunk,
)
from nestd.local.translate.errors import anthropic_error, openai_error, upstream_message
from nestd.local.translate.sse import chunks, encode
from nestd.local.translate.values import JsonObject, integer, new_id, objects, string


def counter() -> "Counter":
    return Counter()


class Counter:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}_{self.count}"


def delta(value: JsonObject, finish: str | None = None) -> JsonObject:
    return {"choices": [{"index": 0, "delta": value, "finish_reason": finish}]}


def call(
    index: int | None = None,
    call_id: str | None = None,
    name: str | None = None,
    arguments: str | None = None,
) -> JsonObject:
    function: JsonObject = {}
    if name is not None:
        function["name"] = name
    if arguments is not None:
        function["arguments"] = arguments
    entry: JsonObject = {"type": "function", "function": function}
    if index is not None:
        entry["index"] = index
    if call_id is not None:
        entry["id"] = call_id
    return entry


def test_text_deltas_come_through_and_empty_ones_are_skipped() -> None:
    decoder = ChunkDecoder(counter())
    assert decoder.feed(delta({"role": "assistant", "content": ""})) == []
    assert decoder.feed(delta({"content": "Hel"})) == [TextDelta("Hel")]
    assert decoder.feed(delta({"content": "lo"}, "stop")) == [TextDelta("lo")]
    assert decoder.finish_reason == "stop"


def test_reasoning_deltas_are_dropped() -> None:
    decoder = ChunkDecoder(counter())
    assert decoder.feed(delta({"reasoning_content": "hmm"})) == []
    assert decoder.feed(delta({"reasoning": "thinking"})) == []


def test_a_tool_call_split_across_chunks_starts_once_and_streams_arguments() -> None:
    decoder = ChunkDecoder(counter())
    first = decoder.feed(delta({"tool_calls": [call(0, "call_a", "Write", '{"pa')]}))
    second = decoder.feed(delta({"tool_calls": [call(0, arguments='th": 1}')]}))
    assert first == [ToolStart(0, "call_a", "Write"), ToolArguments(0, '{"pa')]
    assert second == [ToolArguments(0, 'th": 1}')]


def test_a_chunk_repeating_a_started_call_without_arguments_adds_nothing() -> None:
    decoder = ChunkDecoder(counter())
    decoder.feed(delta({"tool_calls": [call(0, "call_a", "Write")]}))
    assert decoder.feed(delta({"tool_calls": [call(0, "call_a")]})) == []


def test_arguments_before_the_name_wait_for_it() -> None:
    decoder = ChunkDecoder(counter())
    assert decoder.feed(delta({"tool_calls": [call(0, "call_a", arguments="{")]})) == []
    assert decoder.feed(delta({"tool_calls": [call(0, name="Read", arguments="}")]})) == [
        ToolStart(0, "call_a", "Read"),
        ToolArguments(0, "{"),
        ToolArguments(0, "}"),
    ]


def test_a_missing_call_id_gets_a_generated_one() -> None:
    decoder = ChunkDecoder(counter())
    assert decoder.feed(delta({"tool_calls": [call(0, name="Bash")]})) == [
        ToolStart(0, "call_1", "Bash")
    ]


def test_several_tool_calls_in_one_chunk_without_indexes_use_their_positions() -> None:
    decoder = ChunkDecoder(counter())
    ops = decoder.feed(
        delta(
            {
                "tool_calls": [
                    call(call_id="a", name="A", arguments="{}"),
                    call(call_id="b", name="B"),
                ]
            }
        )
    )
    assert ops == [ToolStart(0, "a", "A"), ToolArguments(0, "{}"), ToolStart(1, "b", "B")]


def test_a_new_id_on_a_reused_index_is_a_new_call() -> None:
    decoder = ChunkDecoder(counter())
    decoder.feed(delta({"tool_calls": [call(0, "a", "A", "{}")]}))
    assert decoder.feed(delta({"tool_calls": [call(0, "b", "B", "{}")]})) == [
        ToolStart(1, "b", "B"),
        ToolArguments(1, "{}"),
    ]
    # The same id again continues that call.
    assert decoder.feed(delta({"tool_calls": [call(0, "b", arguments=" ")]})) == [
        ToolArguments(1, " ")
    ]


def test_interleaved_calls_keep_their_own_slots() -> None:
    decoder = ChunkDecoder(counter())
    decoder.feed(delta({"tool_calls": [call(0, "a", "A"), call(1, "b", "B")]}))
    assert decoder.feed(
        delta({"tool_calls": [call(0, arguments="x"), call(1, arguments="y")]})
    ) == [
        ToolArguments(0, "x"),
        ToolArguments(1, "y"),
    ]


def test_usage_is_read_from_its_own_chunk() -> None:
    decoder = ChunkDecoder(counter())
    decoder.feed(
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 7,
                "prompt_tokens_details": {"cached_tokens": 40},
                "completion_tokens_details": {"reasoning_tokens": 3},
            },
        }
    )
    assert decoder.usage == Usage(
        input_tokens=100, output_tokens=7, cached_tokens=40, reasoning_tokens=3
    )


def test_usage_defaults_to_zero_and_a_null_usage_changes_nothing() -> None:
    decoder = ChunkDecoder(counter())
    decoder.feed({"choices": [], "usage": None})
    assert decoder.usage == Usage()


def test_an_error_chunk_is_kept() -> None:
    decoder = ChunkDecoder(counter())
    assert decoder.feed({"error": {"message": "model crashed"}}) == []
    assert decoder.error == "model crashed"
    other = ChunkDecoder(counter())
    other.feed({"error": "out of memory"})
    assert other.error == "out of memory"


def test_odd_chunks_are_ignored() -> None:
    decoder = ChunkDecoder(counter())
    assert decoder.feed({"choices": ["junk"]}) == []
    assert decoder.feed({"choices": [{"delta": None}]}) == []
    assert decoder.feed(delta({"tool_calls": ["junk"]})) == []
    assert decoder.finish_reason is None


def test_completion_chunk_turns_a_whole_reply_into_one_chunk() -> None:
    completion: JsonObject = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "Hi",
                    "tool_calls": [call(call_id="a", name="A")],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 5, "completion_tokens": 1},
    }
    decoder = ChunkDecoder(counter())
    ops = decoder.feed(completion_chunk(completion))
    assert ops == [TextDelta("Hi"), ToolStart(0, "a", "A")]
    assert decoder.finish_reason == "tool_calls"
    assert decoder.usage.input_tokens == 5


def test_completion_chunk_keeps_an_error_and_survives_no_choices() -> None:
    assert completion_chunk({"error": {"message": "bad"}}) == {"error": {"message": "bad"}}
    decoder = ChunkDecoder(counter())
    assert decoder.feed(completion_chunk({"choices": []})) == []


def test_encode_frames_named_and_unnamed_events() -> None:
    assert encode("ping", {"type": "ping"}) == b'event: ping\ndata: {"type":"ping"}\n\n'
    assert encode(None, {"a": 1}) == b'data: {"a":1}\n\n'


async def lines(*values: str) -> AsyncIterator[str]:
    for value in values:
        yield value


async def test_chunks_reads_data_lines_until_done() -> None:
    first = json.dumps({"choices": []})
    found = [
        chunk
        async for chunk in chunks(
            lines(
                ": keep-alive",
                "event: x",
                "",
                f"data: {first}",
                "data:not json",
                "data: [1, 2]",
                'data:{"b":2}',
                "data: [DONE]",
                'data: {"after": true}',
            )
        )
    ]
    assert found == [{"choices": []}, {"b": 2}]


async def test_chunks_ends_with_the_stream_without_done() -> None:
    assert [chunk async for chunk in chunks(lines('data: {"a": 1}'))] == [{"a": 1}]


def test_upstream_message_reads_the_common_error_shapes() -> None:
    assert upstream_message(b'{"error": {"message": "no such model"}}') == "no such model"
    assert upstream_message(b'{"error": "model not loaded"}') == "model not loaded"
    assert upstream_message(b'{"message": "busy"}') == "busy"
    assert upstream_message(b'{"detail": "bad field"}') == "bad field"
    assert upstream_message(b'{"other": 1}') == '{"other": 1}'
    assert upstream_message(b"plain text") == "plain text"
    assert upstream_message(b"") == "no details"
    assert upstream_message(b"x" * 5000) == "x" * 1000


def test_anthropic_error_types_follow_the_status() -> None:
    def kind(status: int) -> JsonValue:
        return string(objects([anthropic_error(status, "m")["error"]])[0]["type"])

    assert anthropic_error(400, "m") == {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "m"},
    }
    assert kind(401) == "authentication_error"
    assert kind(403) == "permission_error"
    assert kind(404) == "not_found_error"
    assert kind(413) == "request_too_large"
    assert kind(422) == "invalid_request_error"
    assert kind(429) == "rate_limit_error"
    assert kind(500) == "api_error"
    assert kind(502) == "api_error"
    assert kind(529) == "overloaded_error"


def test_openai_error_shape() -> None:
    assert openai_error(400, "m") == {
        "error": {"message": "m", "type": "invalid_request_error", "code": None}
    }
    assert openai_error(503, "m") == {
        "error": {"message": "m", "type": "server_error", "code": None}
    }


def test_value_helpers() -> None:
    assert integer(True) == 0
    assert integer(3) == 3
    assert integer(2.0) == 2
    assert integer("3") == 0
    assert new_id("msg").startswith("msg_")
    assert new_id("msg") != new_id("msg")
