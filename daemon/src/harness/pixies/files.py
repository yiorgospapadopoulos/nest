"""A pixie's folder: SOUL.md, MEMORY.md, notes/, archive/ and the chat's workdir/ (D072).

Writes name the hash of the text the writer read, so the user and the pixie editing at
once never lose each other's changes silently.
"""

import hashlib
import re
import shutil
from datetime import date
from pathlib import Path

from harness.pixies.errors import InvalidFileNameError, PixieNotFoundError, StaleFileError
from harness.pixies.models import FileText, SearchHit
from harness.pixies.redact import redact

SOUL_FILE = "SOUL.md"
MEMORY_FILE = "MEMORY.md"
MEMORY_HEADER = "# Memory\n"
MEMORY_BUDGET = 8192
NOTE = re.compile(r"^notes/([a-z0-9][a-z0-9-]{0,63})$")
FACT_PREFIX = "- "
# What the store hands out (uuid4().hex); anything else never becomes a path.
PIXIE_ID = re.compile(r"^[0-9a-f]{32}$")


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _normal(text: str) -> str:
    return text.rstrip("\n") + "\n"


class PixieFiles:
    def __init__(self, root: Path) -> None:
        self._root = root

    def create(self, pixie_id: str, soul: str) -> None:
        folder = self._root / _checked(pixie_id)
        for sub in ("notes", "archive", "workdir"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        (folder / SOUL_FILE).write_text(_normal(soul), encoding="utf-8")
        (folder / MEMORY_FILE).write_text(MEMORY_HEADER, encoding="utf-8")

    def copy(self, source_id: str, target_id: str) -> None:
        """A new pixie's folder with the soul, memory, notes and archive of another; its
        workdir starts empty (B40).
        """
        source = self._folder(source_id)
        target = self._root / _checked(target_id)
        for sub in ("notes", "archive"):
            shutil.copytree(source / sub, target / sub)
        (target / "workdir").mkdir()
        for name in (SOUL_FILE, MEMORY_FILE):
            shutil.copy2(source / name, target / name)

    def remove(self, pixie_id: str) -> None:
        shutil.rmtree(self._root / _checked(pixie_id), ignore_errors=True)

    def workdir(self, pixie_id: str) -> Path:
        return self._folder(pixie_id) / "workdir"

    def read(self, pixie_id: str, name: str) -> FileText:
        path = self._path(pixie_id, name)
        if not path.is_file():
            msg = f"{name} does not exist"
            raise PixieNotFoundError(msg)
        text = path.read_text(encoding="utf-8")
        return FileText(text=text, hash=text_hash(text))

    def write(self, pixie_id: str, name: str, text: str, expected: str | None) -> FileText:
        path = self._path(pixie_id, name)
        if path.is_file():
            current = path.read_text(encoding="utf-8")
            if expected != text_hash(current):
                raise StaleFileError(name, current, text_hash(current))
        elif expected is not None:
            raise StaleFileError(name, "", "")
        normal = _normal(text)
        path.write_text(normal, encoding="utf-8")
        return FileText(text=normal, hash=text_hash(normal))

    def add_fact(self, pixie_id: str, fact: str, today: date) -> FileText:
        path = self._folder(pixie_id) / MEMORY_FILE
        line = f"{FACT_PREFIX}{today.isoformat()}: {redact(' '.join(fact.split()))}\n"
        text = path.read_text(encoding="utf-8") + line
        text = self._archive_overflow(pixie_id, text, today)
        path.write_text(text, encoding="utf-8")
        return FileText(text=text, hash=text_hash(text))

    def forget(self, pixie_id: str, fragment: str) -> int:
        if not fragment.strip():
            return 0
        path = self._folder(pixie_id) / MEMORY_FILE
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        needle = fragment.lower()
        kept = [
            line for line in lines if not (line.startswith(FACT_PREFIX) and needle in line.lower())
        ]
        path.write_text("".join(kept), encoding="utf-8")
        return len(lines) - len(kept)

    def notes(self, pixie_id: str) -> list[str]:
        return sorted(p.stem for p in (self._folder(pixie_id) / "notes").glob("*.md"))

    def search(self, pixie_id: str, query: str) -> list[SearchHit]:
        folder = self._folder(pixie_id)
        needle = query.lower()
        files = [
            folder / MEMORY_FILE,
            *sorted((folder / "notes").glob("*.md")),
            *sorted((folder / "archive").glob("*.md")),
        ]
        return [
            SearchHit(file=path.relative_to(folder).as_posix(), line=line)
            for path in files
            for line in path.read_text(encoding="utf-8").splitlines()
            if needle in line.lower()
        ]

    def _archive_overflow(self, pixie_id: str, text: str, today: date) -> str:
        """Move the oldest facts to this month's archive file until the budget holds."""
        lines = text.splitlines(keepends=True)
        moved: list[str] = []
        while len("".join(lines).encode()) > MEMORY_BUDGET:
            oldest = next((i for i, line in enumerate(lines) if line.startswith(FACT_PREFIX)), None)
            if oldest is None:
                break
            moved.append(lines.pop(oldest))
        if moved:
            archive = self._folder(pixie_id) / "archive" / f"{today:%Y-%m}.md"
            with archive.open("a", encoding="utf-8") as handle:
                handle.writelines(moved)
        return "".join(lines)

    def _folder(self, pixie_id: str) -> Path:
        folder = self._root / _checked(pixie_id)
        if not folder.is_dir():
            msg = f"unknown pixie {pixie_id!r}"
            raise PixieNotFoundError(msg)
        return folder

    def _path(self, pixie_id: str, name: str) -> Path:
        if name == "soul":
            return self._folder(pixie_id) / SOUL_FILE
        if name == "memory":
            return self._folder(pixie_id) / MEMORY_FILE
        match = NOTE.match(name)
        if match is None:
            msg = f"invalid file name {name!r}: use soul, memory or notes/<name>"
            raise InvalidFileNameError(msg)
        return self._folder(pixie_id) / "notes" / f"{match.group(1)}.md"


def _checked(pixie_id: str) -> str:
    if PIXIE_ID.fullmatch(pixie_id) is None:
        msg = f"unknown pixie {pixie_id!r}"
        raise PixieNotFoundError(msg)
    return pixie_id
