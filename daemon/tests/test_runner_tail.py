"""BUG-97: a command's output can be bounded to its last bytes, read as it streams."""

import asyncio
from pathlib import Path

import pytest

from nestd.gitops.runner import CommandError, keeping_tail, output_tail, run_command


def test_no_tail_is_kept_by_default() -> None:
    assert output_tail() is None


async def test_without_a_tail_the_whole_output_is_returned(tmp_path: Path) -> None:
    output = await run_command(["/bin/sh", "-c", "seq 1 5000"], tmp_path)

    assert output.startswith("1\n2\n")
    assert output.endswith("4999\n5000\n")


@pytest.mark.parametrize(
    ("limit", "kept"),
    [
        # The last 20 bytes start inside "199998", so that cut line goes.
        (20, "199999\n200000\n"),
        # The last 21 bytes start just after a newline: nothing is cut.
        (21, "199998\n199999\n200000\n"),
    ],
)
async def test_only_the_last_bytes_are_kept_from_a_line_start(
    tmp_path: Path, limit: int, kept: str
) -> None:
    with keeping_tail(limit):
        assert output_tail() == limit
        # About 1.2 MB, more than one pipe read.
        output = await run_command(["/bin/sh", "-c", "seq 1 200000"], tmp_path)

    assert output_tail() is None
    assert output == kept


async def test_output_shorter_than_the_tail_is_whole(tmp_path: Path) -> None:
    with keeping_tail(1000):
        output = await run_command(["/bin/sh", "-c", "printf 'one\\ntwo'"], tmp_path)

    assert output == "one\ntwo"


async def test_a_tail_that_is_one_long_line_is_dropped_whole(tmp_path: Path) -> None:
    """A cut line could start in the middle of a secret, past what scrubbing recognizes."""
    with keeping_tail(10):
        output = await run_command(["/bin/sh", "-c", "printf 'ghp_%040d' 0"], tmp_path)

    assert output == ""


async def test_the_error_output_is_bounded_too(tmp_path: Path) -> None:
    script = "seq 1 100000 >&2; echo 'HTTP 403: Forbidden' >&2; exit 4"

    with keeping_tail(30), pytest.raises(CommandError) as caught:
        await run_command(["/bin/sh", "-c", script], tmp_path)

    assert caught.value.returncode == 4
    assert caught.value.stderr == "100000\nHTTP 403: Forbidden\n"


async def test_a_bounded_command_that_hangs_is_killed(tmp_path: Path) -> None:
    marker = tmp_path / "finished"

    with keeping_tail(100), pytest.raises(CommandError) as caught:
        await run_command(
            ["/bin/sh", "-c", f"echo started; sleep 0.5 && touch {marker}"],
            tmp_path,
            time_limit=0.1,
        )
    await asyncio.sleep(0.7)

    assert caught.value.stderr == "timed out after 0.1 seconds"
    assert not marker.exists()


def test_a_tail_must_be_positive() -> None:
    with pytest.raises(ValueError, match="positive"):
        keeping_tail(0).__enter__()
