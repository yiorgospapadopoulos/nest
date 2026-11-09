"""Regression (B153 check): a call's result shows what the engine said even where it puts
it outside the usual keys, so a refusal or a command's output is never an empty box.
"""

from typing import cast

import pytest
from pydantic import JsonValue

from nestd.providers.acp_events import AcpStream
from nestd.providers.base import ToolResultBlock
from tests.recording_sink import RecordingSink


@pytest.mark.parametrize(
    ("status", "output", "shown"),
    [
        # Antigravity's command output.
        ("completed", {"combinedOutput": "hello\n", "exitCode": 0}, "hello\n"),
        # Copilot's refusal by its own deny rules.
        ("failed", {"message": "denied due to the following rules: shell(git push)"}, None),
    ],
)
async def test_the_result_shows_the_engines_words(
    status: str, output: dict[str, JsonValue], shown: str | None
) -> None:
    sink = RecordingSink()
    stream = AcpStream(sink, {})
    call: dict[str, JsonValue] = {"toolCallId": "c1", "kind": "execute", "title": "x"}
    await stream.handle(
        "session/update", {"update": {"sessionUpdate": "tool_call", "rawInput": {}, **call}}
    )
    done: dict[str, JsonValue] = {"status": status, "rawOutput": output}
    await stream.handle(
        "session/update", {"update": {"sessionUpdate": "tool_call_update", **call, **done}}
    )

    [result] = [
        block
        for kind, value in sink.calls
        if kind == "message"
        for block in cast("tuple[list[object], object]", value)[0]
        if isinstance(block, ToolResultBlock)
    ]
    expected = shown if shown is not None else next(iter(output.values()))
    assert result.content == expected
    assert result.is_error is (status == "failed")
