"""Which quality gates a set of changed repository paths needs (B100).

A path inside `daemon/`, `web/` or `apple/` runs that part's gate. The design source and
its generator feed every part; the generated files are checked by the daemon's tests, so
they run the daemon as well as their own part. Documentation runs nothing, and any other
path runs everything, so nothing is skipped by mistake.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import PurePosixPath

from nestd.design.icon import ICON_OUTPUTS
from nestd.design.outputs import CSS_OUTPUT, MASCOTS_SWIFT_OUTPUT, MASCOTS_TS_OUTPUT, SWIFT_OUTPUT

# In the order `make check` runs them.
ALL_PARTS = ("daemon", "web", "apple")

_DESIGN_SOURCES = ("design", "daemon/src/nestd/design")
_GENERATED = frozenset(
    str(path)
    for path in (CSS_OUTPUT, SWIFT_OUTPUT, MASCOTS_TS_OUTPUT, MASCOTS_SWIFT_OUTPUT, *ICON_OUTPUTS)
)
_DOCS_FILES = frozenset({"README.md", "LICENSE"})
_DOCS_FOLDERS = ("docs",)


@dataclass(frozen=True)
class Choice:
    """The parts one changed path runs, and why."""

    path: str
    parts: frozenset[str]
    reason: str


@dataclass(frozen=True)
class Selection:
    choices: tuple[Choice, ...]

    @property
    def parts(self) -> tuple[str, ...]:
        return tuple(part for part in ALL_PARTS if self.because(part))

    def because(self, part: str) -> list[Choice]:
        return [choice for choice in self.choices if part in choice.parts]


def _inside(path: str, folder: str) -> bool:
    return PurePosixPath(path).is_relative_to(folder) and path != folder


def classify(path: str) -> Choice:
    if any(_inside(path, folder) for folder in _DESIGN_SOURCES):
        return Choice(path, frozenset(ALL_PARTS), "design source, feeds every part")
    if path in _GENERATED:
        part = PurePosixPath(path).parts[0]
        return Choice(path, frozenset({part, "daemon"}), "generated, checked by the daemon")
    for part in ALL_PARTS:
        if _inside(path, part):
            return Choice(path, frozenset({part}), part)
    if path in _DOCS_FILES or any(_inside(path, folder) for folder in _DOCS_FOLDERS):
        return Choice(path, frozenset(), "documentation")
    return Choice(path, frozenset(ALL_PARTS), "shared or unmapped file")


def select(paths: Iterable[str]) -> Selection:
    return Selection(tuple(classify(path) for path in paths))
