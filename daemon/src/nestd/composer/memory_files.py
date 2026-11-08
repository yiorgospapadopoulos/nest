"""Where each engine reads its instructions, so a `#` memory goes where that engine itself
reads it (B145, match Claude everywhere): Claude Code's CLAUDE.md, Codex's AGENTS.md,
Gemini CLI's GEMINI.md. OpenCode reads AGENTS.md and, without one, CLAUDE.md, so a project
that has only CLAUDE.md keeps getting its memories there.
"""

from dataclasses import dataclass
from pathlib import Path

CLAUDE_MD = "CLAUDE.md"
AGENTS_MD = "AGENTS.md"
GEMINI_MD = "GEMINI.md"
_NAMES: dict[str, tuple[str, ...]] = {
    "claude": (CLAUDE_MD,),
    "codex": (AGENTS_MD,),
    "opencode": (AGENTS_MD, CLAUDE_MD),
    "gemini": (GEMINI_MD,),
    "cursor": (AGENTS_MD,),
}


@dataclass(frozen=True)
class MemoryFile:
    # The project's files the engine reads, first choice first: a memory goes into the
    # first that exists, else the first.
    names: tuple[str, ...]
    # The user's own file for every project, in the same order; empty when the engine
    # keeps them elsewhere than a file.
    user: tuple[Path, ...] = ()

    @property
    def name(self) -> str:
        return self.names[0]

    def project(self, folder: Path) -> Path:
        return _first(tuple(folder / name for name in self.names))

    def for_user(self) -> Path | None:
        return _first(self.user) if self.user else None


def memory_files(
    home: Path | None, claude_dir: Path | None, codex_home: Path | None
) -> dict[str, MemoryFile]:
    """By engine name. A folder that is None has no user file, so tests never write the
    real ones.
    """
    claude_user = () if claude_dir is None else (claude_dir / CLAUDE_MD,)
    users: dict[str, tuple[Path, ...]] = {
        "claude": claude_user,
        "codex": () if codex_home is None else (codex_home / AGENTS_MD,),
        "opencode": (
            *(() if home is None else (home / ".config" / "opencode" / AGENTS_MD,)),
            *claude_user,
        ),
        "gemini": () if home is None else (home / ".gemini" / GEMINI_MD,),
        # Cursor keeps the user's own rules in its settings.
        "cursor": (),
    }
    return {engine: MemoryFile(_NAMES[engine], user) for engine, user in users.items()}


def memory_name(engine: str) -> str:
    """The project file the engine reads its instructions from, as clients name it."""
    return _NAMES.get(engine, (CLAUDE_MD,))[0]


def _first(paths: tuple[Path, ...]) -> Path:
    return next((path for path in paths if path.is_file()), paths[0])
