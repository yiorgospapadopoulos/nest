"""OpenAI Responses to Chat Completions and back."""

import json

from nestd.local.translate.responses_reply import ResponsesReply
from nestd.local.translate.responses_request import chat_request
from nestd.local.translate.values import JsonObject
from tests.test_local_translate_stream import call, counter, delta

CREATED = 1_800_000_000


def test_a_plain_request_keeps_model_limits_and_asks_for_usage() -> None:
    body: JsonObject = {
        "model": "gpt-oss",
        "instructions": "You are Codex.",
        "input": "hi",
        "max_output_tokens": 1000,
        "temperature": 0.1,
        "top_p": 0.5,
        "parallel_tool_calls": True,
        "stream": True,
        "store": False,
        "reasoning": {"effort": "high"},
        "include": ["reasoning.encrypted_content"],
        "prompt_cache_key": "k",
    }
    request = chat_request(body)
    assert request.body == {
        "model": "gpt-oss",
        "messages": [
            {"role": "system", "content": "You are Codex."},
            {"role": "user", "content": "hi"},
        ],
        "max_tokens": 1000,
        "temperature": 0.1,
        "top_p": 0.5,
        "parallel_tool_calls": True,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    assert request.custom_tools == frozenset()


def test_a_non_streaming_request_without_input() -> None:
    assert chat_request({"model": "m"}).body == {"model": "m", "messages": [], "stream": False}


def test_leading_developer_messages_join_the_system_message_and_later_ones_become_user() -> None:
    body: JsonObject = {
        "model": "m",
        "instructions": "Base.",
        "input": [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": "Rules."}],
            },
            {"role": "system", "content": "More rules."},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Go"}]},
            {"type": "message", "role": "developer", "content": "Model changed."},
        ],
    }
    assert chat_request(body).body["messages"] == [
        {"role": "system", "content": "Base.\n\nRules.\n\nMore rules."},
        {"role": "user", "content": "Go"},
        {"role": "user", "content": "Model changed."},
    ]


def test_messages_with_images_and_assistant_text() -> None:
    body: JsonObject = {
        "model": "m",
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": "Look"},
                    {
                        "type": "input_image",
                        "image_url": "data:image/png;base64,AAA",
                        "detail": "auto",
                    },
                    {"type": "input_image"},
                    {"type": "input_file", "file_id": "f"},
                ],
            },
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "A cat.", "annotations": []}],
            },
            {"type": "message", "role": "user", "content": []},
            {"type": "reasoning", "summary": [], "encrypted_content": "x"},
            {"type": "web_search_call"},
            "junk",
        ],
    }
    assert chat_request(body).body["messages"] == [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Look"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}},
            ],
        },
        {"role": "assistant", "content": "A cat."},
    ]


def test_function_calls_join_the_assistant_turn_and_outputs_become_tool_messages() -> None:
    body: JsonObject = {
        "model": "m",
        "input": [
            {"type": "message", "role": "user", "content": "List files"},
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Sure."}],
            },
            {
                "type": "function_call",
                "id": "fc_1",
                "call_id": "call_1",
                "name": "exec_command",
                "arguments": '{"cmd": "ls"}',
            },
            {
                "type": "function_call",
                "call_id": "call_2",
                "name": "exec_command",
                "arguments": "{}",
            },
            {"type": "function_call_output", "call_id": "call_1", "output": "a.txt"},
            {
                "type": "function_call_output",
                "call_id": "call_2",
                "output": [
                    {"type": "input_text", "text": "b"},
                    {"type": "input_text", "text": "c"},
                ],
            },
            {"type": "function_call", "call_id": "call_3", "name": "exec_command"},
        ],
    }
    assert chat_request(body).body["messages"] == [
        {"role": "user", "content": "List files"},
        {
            "role": "assistant",
            "content": "Sure.",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "exec_command", "arguments": '{"cmd": "ls"}'},
                },
                {
                    "id": "call_2",
                    "type": "function",
                    "function": {"name": "exec_command", "arguments": "{}"},
                },
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "a.txt"},
        {"role": "tool", "tool_call_id": "call_2", "content": "b\n\nc"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_3",
                    "type": "function",
                    "function": {"name": "exec_command", "arguments": "{}"},
                }
            ],
        },
    ]


def test_custom_tool_calls_are_function_calls_with_one_input_argument() -> None:
    body: JsonObject = {
        "model": "m",
        "input": [
            {
                "type": "custom_tool_call",
                "call_id": "c1",
                "name": "apply_patch",
                "input": "*** Begin Patch",
            },
            {"type": "custom_tool_call_output", "call_id": "c1", "output": "Done"},
        ],
    }
    assert chat_request(body).body["messages"] == [
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {
                        "name": "apply_patch",
                        "arguments": json.dumps({"input": "*** Begin Patch"}),
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "Done"},
    ]


def test_images_in_a_tool_output_follow_as_a_user_message() -> None:
    body: JsonObject = {
        "model": "m",
        "input": [
            {
                "type": "function_call_output",
                "call_id": "v",
                "output": [{"type": "input_image", "image_url": "data:image/png;base64,QQ"}],
            },
            {"type": "function_call_output", "call_id": "w", "output": None},
        ],
    }
    assert chat_request(body).body["messages"] == [
        {"role": "tool", "tool_call_id": "v", "content": "(image below)"},
        {"role": "tool", "tool_call_id": "w", "content": ""},
        {
            "role": "user",
            "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,QQ"}}],
        },
    ]


def test_function_and_custom_tools_are_offered_and_others_dropped() -> None:
    body: JsonObject = {
        "model": "m",
        "tools": [
            {
                "type": "function",
                "name": "exec_command",
                "description": "Run a command",
                "strict": False,
                "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            },
            {"type": "function", "name": "bare"},
            {
                "type": "custom",
                "name": "apply_patch",
                "description": "Apply a patch.",
                "format": {"type": "grammar", "syntax": "lark", "definition": "start: x"},
            },
            {"type": "custom", "name": "free"},
            {"type": "web_search"},
            {"type": "function"},
        ],
    }
    request = chat_request(body)
    assert request.body["tools"] == [
        {
            "type": "function",
            "function": {
                "name": "exec_command",
                "description": "Run a command",
                "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "bare",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "apply_patch",
                "description": "Apply a patch.\n\nThe input follows this lark grammar:\nstart: x",
                "parameters": {
                    "type": "object",
                    "properties": {"input": {"type": "string", "description": "The raw input."}},
                    "required": ["input"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "free",
                "description": "",
                "parameters": {
                    "type": "object",
                    "properties": {"input": {"type": "string", "description": "The raw input."}},
                    "required": ["input"],
                },
            },
        },
    ]
    assert request.custom_tools == frozenset({"apply_patch", "free"})


def test_tool_choice_maps_each_kind() -> None:
    def choice(value: JsonObject | str) -> JsonObject:
        return chat_request({"model": "m", "tool_choice": value}).body

    assert choice("auto")["tool_choice"] == "auto"
    assert choice("none")["tool_choice"] == "none"
    assert choice("required")["tool_choice"] == "required"
    assert choice({"type": "function", "name": "x"})["tool_choice"] == {
        "type": "function",
        "function": {"name": "x"},
    }
    assert choice({"type": "custom", "name": "apply_patch"})["tool_choice"] == {
        "type": "function",
        "function": {"name": "apply_patch"},
    }
    assert "tool_choice" not in choice("weird")
    assert "tool_choice" not in choice({"type": "allowed_tools"})


def frames(raw: bytes) -> list[JsonObject]:
    found: list[JsonObject] = []
    for frame in raw.decode().strip().split("\n\n"):
        name_line, data_line = frame.split("\n")
        data = json.loads(data_line.removeprefix("data: "))
        assert name_line == f"event: {data['type']}"
        found.append(data)
    return found


def kinds(raw: bytes) -> list[str]:
    return [str(frame["type"]) for frame in frames(raw)]


def reply(custom: frozenset[str] = frozenset()) -> ResponsesReply:
    return ResponsesReply("gpt-oss", custom, CREATED, counter())


def test_created_announces_the_response() -> None:
    assert frames(reply().start()) == [
        {
            "type": "response.created",
            "sequence_number": 0,
            "response": {
                "id": "resp_1",
                "object": "response",
                "created_at": CREATED,
                "status": "in_progress",
                "model": "gpt-oss",
                "output": [],
                "usage": None,
            },
        }
    ]


def test_a_text_reply_streams_as_one_message_item() -> None:
    stream = reply()
    stream.start()
    out = stream.feed(delta({"content": "Hel"})) + stream.feed(delta({"content": "lo"}, "stop"))
    out += stream.feed(
        {
            "choices": [],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 2,
                "prompt_tokens_details": {"cached_tokens": 5},
            },
        }
    )
    out += stream.finish()
    found = frames(out)
    assert [frame["type"] for frame in found] == [
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert [frame["sequence_number"] for frame in found] == list(range(1, 9))
    assert found[0]["item"] == {
        "type": "message",
        "id": "msg_2",
        "role": "assistant",
        "status": "in_progress",
        "content": [],
    }
    assert found[2] == {
        "type": "response.output_text.delta",
        "sequence_number": 3,
        "item_id": "msg_2",
        "output_index": 0,
        "content_index": 0,
        "delta": "Hel",
    }
    assert found[4]["text"] == "Hello"
    message: JsonObject = {
        "type": "message",
        "id": "msg_2",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": "Hello", "annotations": []}],
    }
    assert found[6]["item"] == message
    assert found[7]["response"] == {
        "id": "resp_1",
        "object": "response",
        "created_at": CREATED,
        "status": "completed",
        "model": "gpt-oss",
        "output": [message],
        "usage": {
            "input_tokens": 20,
            "input_tokens_details": {"cached_tokens": 5},
            "output_tokens": 2,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 22,
        },
    }
    assert stream.done


def test_text_then_two_function_calls() -> None:
    stream = reply()
    stream.start()
    out = stream.feed(delta({"content": "Looking."}))
    out += stream.feed(delta({"tool_calls": [call(0, "call_a", "exec_command", '{"cmd"')]}))
    out += stream.feed(delta({"tool_calls": [call(0, arguments=': "ls"}')]}))
    out += stream.feed(
        delta({"tool_calls": [call(1, "call_b", "exec_command", "{}")]}, "tool_calls")
    )
    out += stream.finish()
    found = frames(out)
    assert [frame["type"] for frame in found] == [
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.delta",
        "response.output_item.added",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert found[6]["item"] == {
        "type": "function_call",
        "id": "fc_3",
        "call_id": "call_a",
        "name": "exec_command",
        "arguments": "",
        "status": "in_progress",
    }
    assert found[6]["output_index"] == 1
    assert found[8] == {
        "type": "response.function_call_arguments.delta",
        "sequence_number": 9,
        "item_id": "fc_3",
        "output_index": 1,
        "delta": ': "ls"}',
    }
    assert found[11]["arguments"] == '{"cmd": "ls"}'
    first_call = {
        "type": "function_call",
        "id": "fc_3",
        "call_id": "call_a",
        "name": "exec_command",
        "arguments": '{"cmd": "ls"}',
        "status": "completed",
    }
    assert found[12]["item"] == first_call
    assert found[14]["output_index"] == 2
    output = found[15]["response"]
    assert isinstance(output, dict)
    assert output["output"] == [
        found[5]["item"],
        first_call,
        {
            "type": "function_call",
            "id": "fc_4",
            "call_id": "call_b",
            "name": "exec_command",
            "arguments": "{}",
            "status": "completed",
        },
    ]


def test_a_custom_tool_call_comes_back_as_custom_tool_call() -> None:
    stream = reply(frozenset({"apply_patch"}))
    stream.start()
    patch = json.dumps({"input": "*** Begin Patch\n*** End Patch"})
    out = stream.feed(delta({"tool_calls": [call(0, "c1", "apply_patch", patch[:10])]}))
    out += stream.feed(delta({"tool_calls": [call(0, arguments=patch[10:])]}))
    out += stream.finish()
    found = frames(out)
    assert [frame["type"] for frame in found] == [
        "response.output_item.added",
        "response.output_item.done",
        "response.completed",
    ]
    assert found[0]["item"] == {
        "type": "custom_tool_call",
        "id": "ctc_2",
        "call_id": "c1",
        "name": "apply_patch",
        "input": "",
        "status": "in_progress",
    }
    assert found[1]["output_index"] == 0
    assert found[1]["item"] == {
        "type": "custom_tool_call",
        "id": "ctc_2",
        "call_id": "c1",
        "name": "apply_patch",
        "input": "*** Begin Patch\n*** End Patch",
        "status": "completed",
    }


def test_a_custom_tool_call_with_raw_arguments_keeps_them_as_input() -> None:
    stream = reply(frozenset({"apply_patch"}))
    stream.feed(delta({"tool_calls": [call(0, "c1", "apply_patch", "*** Begin Patch")]}))
    stream.finish()
    stream_two = reply(frozenset({"apply_patch"}))
    stream_two.feed(delta({"tool_calls": [call(0, "c2", "apply_patch", '{"other": 1}')]}))
    stream_two.finish()
    first = stream.response()["output"]
    second = stream_two.response()["output"]
    assert isinstance(first, list)
    assert isinstance(second, list)
    assert [item["input"] for item in first if isinstance(item, dict)] == ["*** Begin Patch"]
    assert [item["input"] for item in second if isinstance(item, dict)] == ['{"other": 1}']


def test_text_after_a_tool_call_opens_a_new_message_item() -> None:
    stream = reply()
    stream.start()
    stream.feed(delta({"tool_calls": [call(0, "a", "f", "{}")]}))
    out = stream.feed(delta({"content": "more"}))
    assert kinds(out) == [
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
    ]
    assert frames(out)[0]["output_index"] == 1


def test_length_ends_as_incomplete() -> None:
    stream = reply()
    stream.start()
    stream.feed(delta({"content": "trunc"}, "length"))
    found = frames(stream.finish())
    assert found[-1]["type"] == "response.incomplete"
    response = found[-1]["response"]
    assert isinstance(response, dict)
    assert response["status"] == "incomplete"
    assert response["incomplete_details"] == {"reason": "max_output_tokens"}


def test_an_empty_reply_completes_with_no_output() -> None:
    stream = reply()
    stream.start()
    assert kinds(stream.finish()) == ["response.completed"]
    assert stream.response()["output"] == []


def test_an_error_chunk_fails_the_response() -> None:
    stream = reply()
    stream.start()
    found = frames(stream.feed({"error": {"message": "model crashed"}}))
    assert len(found) == 1
    assert found[0]["type"] == "response.failed"
    response = found[0]["response"]
    assert isinstance(response, dict)
    assert response["status"] == "failed"
    assert response["error"] == {"code": "server_error", "message": "model crashed"}
    assert stream.done
    assert stream.error == "model crashed"


def test_fail_reports_a_broken_stream() -> None:
    stream = reply()
    stream.start()
    assert kinds(stream.fail("connection lost")) == ["response.failed"]
    assert stream.done
