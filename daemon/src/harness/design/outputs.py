"""Generate the client token files from the token source, or check that they are current."""

from pathlib import Path

from harness.design.css import render_css
from harness.design.loader import TOKENS_FILE, load_tokens
from harness.design.swift import render_swift

CSS_OUTPUT = Path("web/src/generated/tokens.css")
SWIFT_OUTPUT = Path("apple/HarnessKit/Sources/HarnessKit/Generated/DesignTokens.swift")


def render_outputs(root: Path) -> dict[Path, str]:
    """Generated file contents keyed by path relative to the repository root."""
    tokens = load_tokens(root / TOKENS_FILE)
    return {CSS_OUTPUT: render_css(tokens), SWIFT_OUTPUT: render_swift(tokens)}


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
