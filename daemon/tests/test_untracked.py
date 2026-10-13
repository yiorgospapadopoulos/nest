"""SH-08: an untracked file is read only as far as the review shows it."""

from pathlib import Path

from harness.review.untracked import MAX_SHOWN_BYTES, untracked_diff


async def test_a_huge_one_line_file_is_cut_to_what_is_shown(tmp_path: Path) -> None:
    (tmp_path / "dump.json").write_bytes(b"x" * (3 * MAX_SHOWN_BYTES))

    diff = await untracked_diff(tmp_path, "dump.json", 2000)

    assert (diff.additions, diff.truncated, diff.binary) == (1, True, False)
    (hunk,) = diff.hunks
    assert hunk.new_lines == 1
    assert len(hunk.lines[0].text) <= MAX_SHOWN_BYTES


async def test_lines_past_the_shown_ones_are_counted_not_kept(tmp_path: Path) -> None:
    line = b"y" * 999 + b"\n"
    (tmp_path / "log.txt").write_bytes(line * 9999 + b"last line without a newline")

    diff = await untracked_diff(tmp_path, "log.txt", 2000)

    assert (diff.additions, diff.truncated) == (10000, True)
    (hunk,) = diff.hunks
    assert hunk.new_lines == 10000
    assert [x.new_line for x in hunk.lines] == list(range(1, len(hunk.lines) + 1))
    assert len(hunk.lines) <= 2000
    assert all(x.text == "y" * 999 for x in hunk.lines[:-1])


async def test_a_file_ending_in_a_newline_past_the_cut_counts_its_lines(tmp_path: Path) -> None:
    (tmp_path / "many.txt").write_bytes(b"z\n" * 3000)

    diff = await untracked_diff(tmp_path, "many.txt", 2000)

    assert (diff.additions, diff.truncated) == (3000, True)
    assert [x.text for x in diff.hunks[0].lines] == ["z"] * 2000


async def test_a_large_binary_file_is_binary(tmp_path: Path) -> None:
    (tmp_path / "blob.bin").write_bytes(b"\0" + b"a\n" * MAX_SHOWN_BYTES)

    diff = await untracked_diff(tmp_path, "blob.bin", 2000)

    assert (diff.binary, diff.hunks) == (True, [])
