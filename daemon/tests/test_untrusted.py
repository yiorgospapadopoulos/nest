import time

from nestd.prs.untrusted import CUT_MARK, MIN_CUT_CHARS, Block, clean, fit_blocks


def test_cleaning_a_long_run_of_letters_takes_no_time() -> None:
    started = time.monotonic()

    cleaned = clean("b" * 200_000 + " MY_API_TOKEN=s3cret, xpassword: 'hunter2'")

    assert time.monotonic() - started < 2
    assert cleaned.endswith(" MY_API_TOKEN=***, xpassword: '***'")


def test_blocks_that_fit_go_whole() -> None:
    parts, whole = fit_blocks([Block("a:", "one"), Block("b:", "``two``")], 100)

    assert parts == ["a:\n```\none\n```", "b:\n```\n``two``\n```"]
    assert whole == 2


def test_the_first_block_that_does_not_fit_is_cut_and_the_rest_left_out() -> None:
    blocks = [Block("a:", "x" * 50), Block("b:", "y" * 1000), Block("c:", "z")]

    parts, whole = fit_blocks(blocks, 600)

    assert whole == 1
    assert len(parts) == 2
    assert parts[1].startswith("b:\n```\nyyy")
    assert parts[1].endswith(f"{CUT_MARK}\n```")
    assert len("\n\n".join(parts)) <= 600


def test_too_little_room_leaves_the_block_out() -> None:
    blocks = [Block("a:", "x" * 50), Block("b:", "y" * 1000)]

    parts, whole = fit_blocks(blocks, 60 + MIN_CUT_CHARS)

    assert (len(parts), whole) == (1, 1)
