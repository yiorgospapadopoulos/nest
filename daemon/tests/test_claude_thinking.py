from typing import Any

from nestd.providers.claude_thinking import ThinkingTimer


class Ticker:
    """A monotonic time source the test moves by hand, in seconds."""

    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def start(index: int, kind: str = "thinking") -> dict[str, Any]:
    return {"type": "content_block_start", "index": index, "content_block": {"type": kind}}


def stop(index: int) -> dict[str, Any]:
    return {"type": "content_block_stop", "index": index}


def test_a_streamed_thinking_block_takes_from_its_start_to_its_stop() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)

    assert timer.stream(start(0)) is True
    time.now += 8.25
    assert timer.stream(stop(0)) is False
    time.now += 3
    assert timer.took() == 8250


def test_redacted_thinking_counts_and_other_blocks_do_not() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)

    assert timer.stream(start(0, "text")) is None
    assert timer.stream(stop(0)) is None
    assert timer.stream({"type": "content_block_delta", "index": 0}) is None
    assert timer.stream({"type": "content_block_start", "index": 1}) is None
    assert timer.stream(start(2, "redacted_thinking")) is True
    time.now += 1
    assert timer.stream(stop(2)) is False
    assert timer.took() == 1000


def test_blocks_are_matched_in_the_order_they_finished() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)

    timer.stream(start(0))
    time.now += 2
    timer.stream(stop(0))
    timer.stream(start(2))
    time.now += 5
    timer.stream(stop(2))

    assert [timer.took(), timer.took()] == [2000, 5000]


def test_a_block_that_arrives_before_its_stop_is_timed_on_arrival() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)

    timer.stream(start(3))
    timer.stream(start(5))
    time.now += 4
    assert timer.took() == 4000
    # Its stop comes later and no longer counts; the other block still does.
    assert timer.stream(stop(3)) is None
    time.now += 1
    assert timer.stream(stop(5)) is False
    assert timer.took() == 5000


def test_without_stream_timing_a_block_is_timed_from_the_previous_content() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)
    assert timer.took() is None

    timer.mark()
    time.now += 6
    assert timer.took() == 6000
    timer.mark()
    time.now += 0.5
    assert timer.took() == 500


def test_a_new_response_or_the_end_of_a_turn_drops_unmatched_timings() -> None:
    time = Ticker()
    timer = ThinkingTimer(time)

    timer.stream(start(0))
    timer.stream(stop(0))
    timer.stream(start(1))
    timer.stream({"type": "message_start", "message": {}})
    assert timer.took() is None

    timer.mark()
    timer.stream(start(0))
    timer.stream(stop(0))
    timer.reset()
    assert timer.took() is None
