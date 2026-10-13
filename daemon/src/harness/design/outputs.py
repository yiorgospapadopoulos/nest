"""Generate the client token files from the token source, or check that they are current."""

from pathlib import Path

from harness.design.css import render_css
from harness.design.errors import DesignError
from harness.design.loader import TOKENS_FILE, load_tokens
from harness.design.mascots import MASCOTS_FILE, load_mascots
from harness.design.mascots import render_swift as render_mascots_swift
from harness.design.mascots import render_ts as render_mascots_ts
from harness.design.swift import render_swift

CSS_OUTPUT = Path("web/src/generated/tokens.css")
SWIFT_OUTPUT = Path("apple/Sources/HarnessKit/Generated/DesignTokens.swift")
MASCOTS_TS_OUTPUT = Path("web/src/generated/mascots.ts")
MASCOTS_SWIFT_OUTPUT = Path("apple/Sources/HarnessKit/Generated/Mascots.swift")


def render_outputs(root: Path) -> dict[Path, str]:
    """Generated file contents keyed by path relative to the repository root."""
    tokens = load_tokens(root / TOKENS_FILE)
    try:
        mascots = load_mascots(root / MASCOTS_FILE)
    except ValueError as error:
        raise DesignError(str(error)) from error
    return {
        CSS_OUTPUT: render_css(tokens),
        SWIFT_OUTPUT: render_swift(tokens),
        MASCOTS_TS_OUTPUT: render_mascots_ts(mascots),
        MASCOTS_SWIFT_OUTPUT: render_mascots_swift(mascots),
    }


def generate(root: Path) -> list[Path]:
    outputs = render_outputs(root)
    for relative, content in outputs.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return list(outputs)


def stale_outputs(root: Path) -> list[str]:
    """One message per generated file that is missing or differs from the token source."""
    problems: list[str] = []
    for relative, content in render_outputs(root).items():
        target = root / relative
        if not target.is_file():
            problems.append(f"{relative} is missing")
        elif target.read_text(encoding="utf-8") != content:
            problems.append(f"{relative} is out of date")
    return problems
