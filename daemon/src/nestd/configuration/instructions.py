"""Claude's CLAUDE.md and the shared AGENTS.md (B97).

Claude uses the shared instructions when its CLAUDE.md has the import line
`@<absolute path of AGENTS.md>` on a line of its own; the rest of CLAUDE.md is Claude's own.
"""


def has_import(text: str, line: str) -> bool:
    return any(row.strip() == line for row in text.splitlines())


def without_import(text: str, line: str) -> str:
    """The text with every import line gone, and the blank lines it leaves at the top."""
    rows = [row for row in text.splitlines(keepends=True) if row.strip() != line]
    return "".join(rows).lstrip("\n")


def with_import(text: str, line: str) -> str:
    """The import line first, then the text as it was; unchanged when it imports already."""
    if has_import(text, line):
        return text
    return f"{line}\n" + (f"\n{text}" if text.strip() else "")


def own_instructions(claude_md: str, line: str) -> str:
    """What CLAUDE.md says apart from the import line, trimmed."""
    return without_import(claude_md, line).strip()
