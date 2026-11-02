"""B115: the words every client shows for a measured value and its change."""

import pytest

from nestd.perf.formatting import Better, Unit, change, value_text


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        (39_712, "tokens", "39.7k"),
        (850, "tokens", "850"),
        (1_500_000, "tokens", "1.5M"),
        (812, "ms", "812 ms"),
        (2_400, "ms", "2.4 s"),
        (102_000, "ms", "1 min 42 s"),
        (2_100_000, "bytes", "2.1 MB"),
        (91.4, "percent", "91%"),
        (4.5, "percent", "4.5%"),
        (3.4, "count", "3.4"),
        (None, "ms", "-"),
    ],
)
def test_values(value: float | None, unit: Unit, text: str) -> None:
    assert value_text(value, unit) == text


@pytest.mark.parametrize(
    ("value", "previous", "unit", "better", "expected"),
    [
        # Tokens change by an amount, timings relative to before.
        (21_200, 20_000, "tokens", "lower", ("▲ 1.2k", "up", "worse")),
        (1_800, 2_400, "ms", "lower", ("▼ 25%", "down", "better")),
        # A percent metric changes by points.
        (88, 91, "percent", "higher", ("▼ 3%", "down", "worse")),
        # Tiny changes and equal values are no change.
        (20_050, 20_000, "tokens", "lower", ("0%", "none", "same")),
        (0, 0, "count", "lower", ("0%", "none", "same")),
        # From nothing there is no share: the amount.
        (2_000, 0, "ms", "lower", ("▲ 2.0 s", "up", "worse")),
        # Neither better nor worse.
        (300, 200, "count", "none", ("▲ 50%", "up", "same")),
    ],
)
def test_changes(
    value: float, previous: float, unit: Unit, better: Better, expected: tuple[str, str, str]
) -> None:
    assert change(value, previous, unit, better) == expected
