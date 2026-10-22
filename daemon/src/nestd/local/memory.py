"""Whether a local model fits this Mac's memory (B106): a model's weights are loaded into
memory whole, so one that takes much of it slows other work or stalls the Mac.
"""

import os

# Above this share of the memory a model is flagged.
WARN_SHARE = 0.4
_GB = 1024**3


def mac_memory() -> int | None:
    """This Mac's memory in bytes; None when the system does not say."""
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (ValueError, OSError):
        return None


def memory_warning(size: int | None, total: int | None) -> str | None:
    """One sentence when the model's `size` on disk is over WARN_SHARE of `total`."""
    if size is None or total is None or size <= total * WARN_SHARE:
        return None
    return (
        f"Needs about {round(size / _GB)} GB of this Mac's {round(total / _GB)} GB:"
        " other work may slow down or the Mac may stall."
    )
