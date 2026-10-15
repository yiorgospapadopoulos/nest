"""Add a `#` memory to a CLAUDE.md, as Claude Code's memory shortcut does (B59)."""

import asyncio
from pathlib import Path


async def append_memory(path: Path, text: str) -> Path:
    """Append `- text` (on one line) to the file, creating it when missing. A linked file
    writes its target. Returns the file written.
    """
    line = f"- {' '.join(text.split())}\n"
    return await asyncio.to_thread(_append, path, line)


def _append(link_or_file: Path, line: str) -> Path:
    path = link_or_file.resolve() if link_or_file.is_symlink() else link_or_file
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    separator = "\n" if existing and not existing.endswith("\n") else ""
    with path.open("a", encoding="utf-8") as file:
        file.write(separator + line)
    return path
