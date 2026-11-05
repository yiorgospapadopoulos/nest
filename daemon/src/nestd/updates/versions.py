"""Which registry versions count as an update: stable ones only, strictly newer."""

import re

# Plain release numbers: a prerelease, dev, post or local tag on either side never counts.
_STABLE = re.compile(r"\d+(?:\.\d+)*")


def stable(version: str) -> tuple[int, ...] | None:
    """The release numbers of a stable version, else None."""
    if _STABLE.fullmatch(version) is None:
        return None
    return tuple(int(part) for part in version.split("."))


def is_newer(candidate: str, current: str) -> bool:
    """Whether `candidate` is a stable release after `current`, itself a stable one."""
    new, old = stable(candidate), stable(current)
    if new is None or old is None:
        return False
    width = max(len(new), len(old))
    return new + (0,) * (width - len(new)) > old + (0,) * (width - len(old))
