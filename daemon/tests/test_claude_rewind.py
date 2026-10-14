"""IMP-02: runs keep file checkpoints, and files can be restored to before a user message."""

from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import TextBlock, UserMessage

from harness.providers.base import RewindResult, SessionSpec, UserInput
from tests.async_support import until
from tests.test_claude_provider import RESULT, Opened


async def test_runs_keep_checkpoints_and_echo_the_users_messages(tmp_path: Path) -> None:
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))

    assert client.options.enable_file_checkpointing is True
    assert client.options.extra_args["replay-user-messages"] is None


async def test_without_a_mode_the_run_passes_none(tmp_path: Path) -> None:
    """IMP-06: Claude Code then applies its own `defaultMode`."""
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, None))

    assert client.options.permission_mode is None


async def test_the_echo_of_a_sent_message_reports_its_checkpoint(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))

    await run.send(UserInput(text="Fix it"))
    client.push(UserMessage(content=[TextBlock("Fix it")], uuid="msg-1"), RESULT)
    await until(lambda: any(name == "result" for name, _ in opened.sink.calls))
    await run.close()

    assert [call for call in opened.sink.calls if call[0] in ("checkpoint", "message")] == [
        ("checkpoint", "msg-1")
    ]


@pytest.mark.parametrize(
    ("response", "result"),
    [
        (
            {"canRewind": True, "filesChanged": ["a.py", "b.py"], "insertions": 3, "deletions": 1},
            RewindResult(
                can_rewind=True, files_changed=["a.py", "b.py"], insertions=3, deletions=1
            ),
        ),
        (
            {"canRewind": False, "error": "No file checkpoint found for this message."},
            RewindResult(can_rewind=False, error="No file checkpoint found for this message."),
        ),
        (
            {"canRewind": "yes", "filesChanged": [1, "b.py"], "insertions": "3", "error": 4},
            RewindResult(can_rewind=False, files_changed=["b.py"]),
        ),
        ({"canRewind": True, "filesChanged": "a.py"}, RewindResult(can_rewind=True)),
    ],
)
async def test_a_preview_says_what_restoring_would_change(
    tmp_path: Path, response: dict[str, Any], result: RewindResult
) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    client.control.response = response

    preview = await run.rewind_files("msg-1", dry_run=True)

    assert preview == result
    assert client.control.requests == [
        {"subtype": "rewind_files", "user_message_id": "msg-1", "dry_run": True}
    ]


async def test_restoring_sends_the_request_without_dry_run(tmp_path: Path) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    client.control.response = {"canRewind": True, "filesChanged": ["a.py"]}

    restored = await run.rewind_files("msg-1", dry_run=False)

    assert restored == RewindResult(can_rewind=True, files_changed=["a.py"])
    assert client.control.requests[0]["dry_run"] is False


async def test_a_refused_restore_says_why(tmp_path: Path) -> None:
    """The engine answers an impossible restore with an error, which the SDK raises."""
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    client.control.error = Exception("Failed to rewind: no checkpoint")

    restored = await run.rewind_files("msg-1", dry_run=False)

    assert restored == RewindResult(can_rewind=False, error="Failed to rewind: no checkpoint")


async def test_a_run_that_lost_its_connection_cannot_restore(tmp_path: Path) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    client._query = None  # pyright: ignore[reportPrivateUsage]

    restored = await run.rewind_files("msg-1", dry_run=True)

    assert restored == RewindResult(can_rewind=False, error="the agent is not connected")
