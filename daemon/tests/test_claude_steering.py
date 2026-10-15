"""B59: the Claude run writes messages into a running turn, takes them back, and resumes a
conversation cut before one of its user messages.
"""

import json
from pathlib import Path
from uuid import uuid4

import pytest
from claude_agent_sdk import TextBlock, UserMessage

from nestd.claude_sessions.location import encode_folder
from nestd.providers.base import ForkPoint, SessionSpec, UserInput
from nestd.providers.claude import ClaudeProvider
from nestd.providers.claude_fork import fork_point
from tests.async_support import until
from tests.test_claude_provider import RESULT, Opened

MESSAGE_ID = "0123456789abcdef0123456789abcdef"
ENGINE_UUID = "01234567-89ab-cdef-0123-456789abcdef"


async def test_a_steered_message_carries_its_uuid_and_its_echo_is_reported(
    tmp_path: Path,
) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))

    await run.send(UserInput(text="Fix it"))
    await run.steer(UserInput(text="also the docs"), MESSAGE_ID)
    client.push(
        UserMessage(content=[TextBlock("Fix it")], uuid="msg-1"),
        UserMessage(content=[TextBlock("also the docs")], uuid=ENGINE_UUID),
        RESULT,
    )
    await until(lambda: any(name == "result" for name, _ in opened.sink.calls))
    await run.close()

    assert run.steers is True
    steered = client.prompts[1]
    assert steered["uuid"] == ENGINE_UUID
    assert steered["message"]["content"] == [{"type": "text", "text": "also the docs"}]
    assert [c for c in opened.sink.calls if c[0] in ("checkpoint", "message_taken")] == [
        ("checkpoint", "msg-1"),
        ("message_taken", (MESSAGE_ID, ENGINE_UUID)),
    ]


async def test_a_second_echo_of_a_steered_message_is_not_reported_again(tmp_path: Path) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))

    await run.steer(UserInput(text="also"), MESSAGE_ID)
    echo = UserMessage(content=[TextBlock("also")], uuid=ENGINE_UUID)
    client.push(echo, echo, RESULT)
    await until(lambda: any(name == "result" for name, _ in opened.sink.calls))
    await run.close()

    assert [c for c in opened.sink.calls if c[0] == "message_taken"] == [
        ("message_taken", (MESSAGE_ID, ENGINE_UUID))
    ]


@pytest.mark.parametrize(
    ("response", "withdrawn"),
    [({"cancelled": True}, True), ({"cancelled": False}, False), ({}, False)],
)
async def test_a_message_is_taken_back_until_the_engine_reads_it(
    tmp_path: Path, response: dict[str, object], withdrawn: bool
) -> None:
    opened = Opened(tmp_path)
    run, client = await opened.open(SessionSpec(tmp_path, "default"))
    await run.steer(UserInput(text="also"), MESSAGE_ID)
    client.control.response = dict(response)

    taken_back = await run.withdraw(MESSAGE_ID)
    client.push(UserMessage(content=[TextBlock("also")], uuid=ENGINE_UUID), RESULT)
    await until(lambda: any(name == "result" for name, _ in opened.sink.calls))
    await run.close()

    assert taken_back is withdrawn
    assert client.control.requests == [
        {"subtype": "cancel_async_message", "message_uuid": ENGINE_UUID}
    ]
    # A message taken back is never reported read, even if an echo came anyway.
    reported = [c for c in opened.sink.calls if c[0] == "message_taken"]
    assert bool(reported) is not withdrawn


async def test_a_failed_take_back_counts_as_read(tmp_path: Path) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    client.control.error = RuntimeError("cancel_async_message is not supported")

    assert await run.withdraw(MESSAGE_ID) is False
    await run.close()


async def test_nothing_is_taken_back_before_the_client_connects(tmp_path: Path) -> None:
    run, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default"))
    client._query = None  # pyright: ignore[reportPrivateUsage]

    assert await run.withdraw(MESSAGE_ID) is False
    await run.close()


async def test_a_cut_conversation_resumes_into_a_fork(tmp_path: Path) -> None:
    _, client = await Opened(tmp_path).open(
        SessionSpec(tmp_path, "default", resume_id="sdk-1", resume_at="a-9", drops_turn="u-10")
    )

    assert client.options.resume == "sdk-1"
    assert client.options.fork_session is True
    assert client.options.resume_session_at == "a-9"
    assert client.options.resume_drops_turn == "u-10"


async def test_a_plain_resume_does_not_fork(tmp_path: Path) -> None:
    _, client = await Opened(tmp_path).open(SessionSpec(tmp_path, "default", resume_id="sdk-1"))

    assert client.options.fork_session is False
    assert client.options.resume_session_at is None
    assert client.options.resume_drops_turn is None


def write_transcript(claude_dir: Path, cwd: Path, session_id: str, entries: list[object]) -> Path:
    folder = claude_dir / "projects" / encode_folder(cwd)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{session_id}.jsonl"
    lines = [entry if isinstance(entry, str) else json.dumps(entry) for entry in entries]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def test_the_fork_point_is_the_parent_of_the_message(tmp_path: Path) -> None:
    claude_dir, cwd, session_id = tmp_path / "claude", tmp_path / "repo", str(uuid4())
    write_transcript(
        claude_dir,
        cwd,
        session_id,
        [
            {"type": "user", "uuid": "u-1", "parentUuid": None},
            {"type": "assistant", "uuid": "a-1", "parentUuid": "u-1"},
            "not json, mentions u-2",
            ["u-2"],
            {"type": "system", "uuid": "s-1", "parentUuid": "a-1"},
            {"type": "assistant", "uuid": "a-3", "parentUuid": "u-2"},
            {"type": "user", "uuid": "u-2", "parentUuid": "s-1"},
        ],
    )
    provider = ClaudeProvider(tmp_path / "gh", claude_dir=claude_dir)

    assert await provider.fork_point(cwd, session_id, "u-2") == ForkPoint("s-1")
    # The first message keeps nothing.
    assert await provider.fork_point(cwd, session_id, "u-1") == ForkPoint(None)
    assert await provider.fork_point(cwd, session_id, "u-9") is None
    assert await provider.fork_point(cwd, str(uuid4()), "u-2") is None


async def test_without_a_claude_folder_there_is_no_fork_point(tmp_path: Path) -> None:
    provider = ClaudeProvider(tmp_path / "gh")

    assert await provider.fork_point(tmp_path, "sdk-1", "u-1") is None


def test_a_missing_projects_folder_has_no_fork_point(tmp_path: Path) -> None:
    assert fork_point(tmp_path / "none", tmp_path, "sdk-1", "u-1") is None


def test_an_unreadable_transcript_has_no_fork_point(tmp_path: Path) -> None:
    claude_dir, cwd = tmp_path / "claude", tmp_path / "repo"
    path = write_transcript(claude_dir, cwd, "sdk-1", [])
    path.unlink()
    path.mkdir()

    assert fork_point(claude_dir / "projects", cwd, "sdk-1", "u-1") is None
