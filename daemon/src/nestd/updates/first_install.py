"""A first install's newest engines (D193), for `release/install.sh`.

    python -m nestd.updates.first_install <requirements.txt> <rest.txt>

Asks PyPI for the newest Claude Code and Codex. Each one with a newer stable release than
the release pins is printed as `package==version`, and the release's requirements go to
`rest.txt` without it, hashes kept, for the installer to install before the newest ones.
Exits 1, printing nothing, when none is newer or PyPI cannot be asked: the installer then
installs the release's own engines. Standard library only, as the daemon's packages are
not installed yet when it runs.
"""

import json
import re
import sys
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from nestd.updates.pypi import PYPI_ENGINES, PYPI_URL, newest_in
from nestd.updates.versions import is_newer

ASK_TIME_LIMIT = 20.0
# A requirement's first line, as `uv export` writes it: `name==version`, maybe a marker.
_PINNED = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s;\\]+)")

type Newest = Callable[[str], str | None]


def ask_pypi(package: str) -> str | None:
    url = PYPI_URL.format(package=package)
    with urllib.request.urlopen(url, timeout=ASK_TIME_LIMIT) as response:  # noqa: S310 (a fixed https address)
        return newest_in(json.load(response), package)


def pinned(requirements: str) -> dict[str, str]:
    """Package to version, for every requirement pinned with `==`."""
    found: dict[str, str] = {}
    for line in requirements.splitlines():
        match = _PINNED.match(line)
        if match is not None:
            found[match.group(1).lower().replace("_", "-")] = match.group(2)
    return found


def without(requirements: str, packages: Sequence[str]) -> str:
    """The requirements with these packages' entries left out: each entry is its first
    line and the indented lines under it (hashes, `# via` notes).
    """
    kept: list[str] = []
    dropping = False
    for line in requirements.splitlines(keepends=True):
        if line[:1] not in (" ", "\t"):
            match = _PINNED.match(line)
            name = match.group(1).lower().replace("_", "-") if match else None
            dropping = name in packages
        if not dropping:
            kept.append(line)
    return "".join(kept)


def newer_engines(requirements: str, newest: Newest) -> dict[str, str]:
    """Each engine with a newer stable release than the requirements pin, to that one."""
    pins: Mapping[str, str] = pinned(requirements)
    newer: dict[str, str] = {}
    for package in PYPI_ENGINES:
        have = pins.get(package)
        latest = newest(package)
        if have is not None and latest is not None and is_newer(latest, have):
            newer[package] = latest
    return newer


def main(args: Sequence[str], newest: Newest = ask_pypi) -> int:
    source, rest = Path(args[0]), Path(args[1])
    requirements = source.read_text(encoding="utf-8")
    try:
        newer = newer_engines(requirements, newest)
    except (OSError, ValueError) as error:
        print(f"could not ask PyPI: {error}", file=sys.stderr)
        return 1
    if not newer:
        return 1
    rest.write_text(without(requirements, list(newer)), encoding="utf-8")
    for package, version in newer.items():
        print(f"{package}=={version}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
