"""What every template shares: the document with the bridge's shim first, Nest's design tokens
as CSS variables in both themes (and light ones for printing), the pinned libraries, the
script wrapper, and data embedded so nothing in it can end its element.
"""

import json
from collections.abc import Mapping
from functools import cache
from html import escape
from importlib.resources import files
from typing import Any, cast

from nestd.artifacts.bridge import SHIM_TAG, init_tag, json_script

# Colors only the templates use (light, dark), from design/tokens.toml like page.py's PALETTE:
# mac.window_opaque, the graphite accent and its text, and status.failed's text.
EXTRA_PALETTE: dict[str, tuple[str, str]] = {
    "surface": ("#f8f8f6", "#171717"),
    "accent": ("#2b2b2e", "#e6e6e9"),
    "on-accent": ("#ffffff", "#141416"),
    "danger": ("#bd2c27", "#ff8f88"),
}

_PACKAGE = "nestd.artifacts.templates"


def resource(name: str) -> str:
    return (files(_PACKAGE) / name).read_text(encoding="utf-8")


# page.py renders these templates, so its values are imported where they are first needed,
# once both modules are loaded.


@cache
def _tokens() -> str:
    from nestd.artifacts.page import FONTS, PALETTE

    palette = {**PALETTE, **EXTRA_PALETTE}

    def block(theme: int, indent: str) -> str:
        return "\n".join(f"{indent}--nest-{name}: {pair[theme]};" for name, pair in palette.items())

    fonts = f"  --nest-font: {FONTS['system']};\n  --nest-mono: {FONTS['mono']};"
    return (
        f":root {{\n  color-scheme: light dark;\n{block(0, '  ')}\n{fonts}\n}}\n"
        f"@media (prefers-color-scheme: dark) {{\n  :root {{\n{block(1, '    ')}\n  }}\n}}\n"
        f"@media print {{\n  :root {{\n    color-scheme: light;\n{block(0, '    ')}\n  }}\n}}\n"
    )


def libraries(count: int) -> tuple[str, ...]:
    """The first `count` of page.py's pinned libraries: marked, Mermaid, highlight.js."""
    from nestd.artifacts.page import LIBRARIES

    return LIBRARIES[:count]


def diagrams() -> str:
    """Mermaid's variables in Nest's colors, light then dark, as page.py gives them."""
    from nestd.artifacts.page import MERMAID

    return f"var DIAGRAMS = {json.dumps(list(MERMAID))};\n"


# Seconds-long waits are for the libraries: when their scripts have not let the page's own
# script start within this time, the page shows its source as it is (nest-fallback).
FALLBACK_MS = 6000
BOOT_TAG = (
    "<script>setTimeout(function () {\n"
    "  var classes = document.documentElement.classList;\n"
    '  if (!classes.contains("nest-ready") && !classes.contains("nest-started")) {\n'
    '    classes.add("nest-fallback");\n'
    "  }\n"
    f"}}, {FALLBACK_MS});</script>"
)
LOADING = '<div class="nest-loading" role="status" aria-label="Loading"><span></span></div>'


def script(*parts: str) -> str:
    """One strict function around the template's script parts, so nothing leaks to `window`.
    It marks the page started (no fallback timer then), and a failure shows the fallback.
    """
    return (
        '(function () {\n"use strict";\n'
        'document.documentElement.classList.add("nest-started");\n'
        "try {\n" + "".join(parts) + "\n} catch (error) {\n"
        '  document.documentElement.classList.add("nest-fallback");\n'
        "}\n})();"
    )


def page(
    *,
    title: str,
    css: str,
    body: str,
    code: str,
    libraries: tuple[str, ...] = (),
    init: Mapping[str, object] | None = None,
    attrs: str = "",
    loading: bool = False,
) -> str:
    """A whole document: the shim first in the head (its init data, when given, right
    before it), the tokens and styles, the body, then the libraries and the template's script
    last, so the body is there when it runs. A page with `loading` shows nothing half built
    until its script marks it ready (loading.css).
    """
    shim = (init_tag(init) if init is not None else "") + SHIM_TAG
    scripts = "".join(f'<script src="{url}"></script>\n' for url in libraries)
    boot = f"{BOOT_TAG}\n" if loading else ""
    styles = resource("loading.css") if loading else ""
    ring = f"{LOADING}\n" if loading else ""
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<meta name="color-scheme" content="light dark">\n{shim}\n{boot}'
        f"<title>{escape(title)}</title>\n"
        f"<style>\n{_tokens()}{resource('base.css')}{styles}{css}</style>\n</head>\n"
        f"<body{attrs}>\n{ring}{body}\n{scripts}<script>{code}</script>\n</body>\n</html>\n"
    )


def source(element_id: str, text: str) -> str:
    """Text in a `<pre>`, escaped: nothing in it can close the element or open a tag. The
    parser drops one newline right after `<pre>`, so a leading one of the text is kept.
    """
    return f'<pre id="{element_id}">\n{escape(text, quote=False)}</pre>'


def json_data(element_id: str, data: object) -> str:
    """Data for the template's script, in a JSON script element nothing in it can end."""
    return json_script(element_id, data)


def clean(text: str) -> str:
    """A string from the agent's JSON with lone surrogates (valid in JSON, not in UTF-8)
    replaced, so the page can always be sent.
    """
    return text.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


def parse(content: str) -> dict[str, Any] | None:
    """The agent's JSON object, or None when it is not one."""
    try:
        data: object = json.loads(content)
    except (ValueError, RecursionError):
        return None
    return cast("dict[str, Any]", data) if isinstance(data, dict) else None


def items(data: dict[str, Any] | None, key: str) -> list[dict[str, Any]]:
    """The objects in a list field; anything else in it is left out."""
    found: object = data.get(key) if data is not None else None
    if not isinstance(found, list):
        return []
    values = cast("list[object]", found)
    return [cast("dict[str, Any]", item) for item in values if isinstance(item, dict)]


def text(item: dict[str, Any], key: str) -> str:
    """A string field, cleaned; empty when missing or not a string."""
    value = item.get(key)
    return clean(value) if isinstance(value, str) else ""


def number(item: dict[str, Any], key: str, low: float, high: float) -> float | None:
    """A number field within [low, high], else None."""
    value = item.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if low <= value <= high else None


def figure(value: float) -> str:
    """A number as CSS and people write it: 8, 1.5."""
    return f"{value:g}"
