import pytest

from nestd.prs.summary import pr_summary
from nestd.review.models import DiffStats

STATS = DiffStats(files=3, additions=40, deletions=2)


def test_two_summary_lines_and_the_stats() -> None:
    text = "## Done\n\n- **Fixed** the `login` bug\n- Added tests\n- Updated docs"

    assert pr_summary(text, STATS) == ("Done\nFixed the login bug\n3 files changed, +40 -2")


def test_without_a_summary_only_the_stats() -> None:
    assert pr_summary(None, DiffStats(files=1, additions=1, deletions=0)) == (
        "1 file changed, +1 -0"
    )


@pytest.mark.parametrize(
    ("text", "first"),
    [
        ("1. First step", "First step"),
        ("2) Second", "Second"),
        ("> quoted", "quoted"),
        ("---\nAfter a rule", "After a rule"),
        ("* star bullet", "star bullet"),
        ("-5 degrees is cold", "-5 degrees is cold"),
    ],
)
def test_leading_markup_is_dropped(text: str, first: str) -> None:
    assert pr_summary(text, STATS).splitlines()[0] == first


def test_long_lines_are_cut() -> None:
    line = pr_summary("x" * 300, STATS).splitlines()[0]

    assert len(line) == 120
    assert line.endswith("…")
