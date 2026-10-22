"""B106: a model too big for this Mac's memory is flagged before it is added."""

import os

import pytest

from nestd.local.memory import mac_memory, memory_warning

GB = 1024**3


def test_a_model_over_40_percent_of_memory_is_flagged() -> None:
    assert memory_warning(12 * GB, 24 * GB) == (
        "Needs about 12 GB of this Mac's 24 GB: other work may slow down or the Mac may stall."
    )


@pytest.mark.parametrize(
    ("size", "total"),
    [(9 * GB, 24 * GB), (None, 24 * GB), (12 * GB, None)],
)
def test_a_model_that_fits_or_is_unknown_is_not(size: int | None, total: int | None) -> None:
    assert memory_warning(size, total) is None


def test_this_macs_memory_is_read_from_the_system() -> None:
    assert mac_memory() == os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")


def test_a_system_that_does_not_say_has_no_memory_figure(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_name: str) -> int:
        raise ValueError("unknown")

    monkeypatch.setattr(os, "sysconf", refuse)

    assert mac_memory() is None
