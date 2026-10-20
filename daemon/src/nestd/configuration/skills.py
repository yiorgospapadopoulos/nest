"""Skill folders on disk (B97): a folder with a SKILL.md is a skill, at any depth."""

import json
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from nestd.claude_code.extensions import front_matter
from nestd.configuration.errors import ChangedOnDiskError
from nestd.configuration.files import write_text

SKILL_FILE = "SKILL.md"
NAME_PATTERN = r"^[a-z0-9][a-z0-9-]{0,63}$"
# claude.ai skills that drive Claude's own apps; Nest switches them off for Codex.
CLAUDE_ONLY = frozenset({"chrome-browser", "computer-use", "built-in-browser"})
_NAME = re.compile(NAME_PATTERN)


@dataclass(frozen=True)
class FoundSkill:
    # The folder's name, which Nest's API uses.
    name: str
    description: str | None
    file: Path

    @property
    def folder(self) -> Path:
        return self.file.parent


def find_skills(root: Path) -> list[FoundSkill]:
    """Every skill under `root`, links followed once, sorted by name then path."""
    found: list[FoundSkill] = []
    seen: set[Path] = set()
    _walk(root, found, seen)
    return sorted(found, key=lambda skill: (skill.name, str(skill.file)))


def _walk(folder: Path, found: list[FoundSkill], seen: set[Path]) -> None:
    real = folder.resolve()
    if real in seen or not folder.is_dir():
        return
    seen.add(real)
    file = folder / SKILL_FILE
    if file.is_file():
        fields = front_matter(file.read_text(encoding="utf-8", errors="replace"))
        found.append(FoundSkill(folder.name, fields.get("description"), file))
        return
    for entry in sorted(os.scandir(folder), key=lambda entry: entry.name):
        if not entry.name.startswith("."):
            _walk(Path(entry.path), found, seen)


def valid_name(name: str) -> bool:
    return _NAME.match(name) is not None


def create_skill(root: Path, name: str, description: str) -> Path:
    """`<root>/<name>/SKILL.md` with front matter; 409 when the folder exists."""
    folder = root / name
    if folder.exists() or folder.is_symlink():
        msg = f"a skill named {name!r} exists already"
        raise ChangedOnDiskError(msg, None)
    summary = " ".join(description.split())
    text = f"---\nname: {name}\ndescription: {json.dumps(summary, ensure_ascii=False)}\n---\n\n"
    file = folder / SKILL_FILE
    write_text(file, text)
    return file


def move_skill(folder: Path, destination: Path) -> None:
    """Move a skill folder; a link is recreated at `destination` pointing where it did
    (as an absolute path) and removed from where it was, its target untouched.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if folder.is_symlink():
        target = folder.readlink()
        destination.symlink_to(target if target.is_absolute() else _normal(folder.parent / target))
        folder.unlink()
    else:
        shutil.move(folder, destination)


def _normal(path: Path) -> Path:
    return Path(os.path.normpath(path))
