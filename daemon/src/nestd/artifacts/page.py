"""The document a client shows in its sandbox for an artifact version (B82, B88). An HTML
artifact is shown as saved with the page's own files inlined (D117); every other kind is
built by Nest's templates from the agent's data. Each gets the bridge's shim before any page
script, with what the page stored and its files as the shim's initial data. The colors,
fonts, libraries and diagram colors here are the ones the templates use.
"""

import base64

from nestd.artifacts import bridge, templates
from nestd.artifacts.files import FileData
from nestd.artifacts.inline import inline
from nestd.artifacts.models import ArtifactKind

LIBRARIES = (
    "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js",
    "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js",
    "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js",
)

# Light and dark values of Nest's design tokens (design/tokens.toml; a test keeps them equal).
PALETTE: dict[str, tuple[str, str]] = {
    "bg": ("#eeeeec", "#0c0c0d"),
    "text": ("#1a1b20", "#f2f3f7"),
    "text-2": ("rgba(26,27,32,0.68)", "rgba(242,243,247,0.7)"),
    "text-3": ("rgba(26,27,32,0.64)", "rgba(242,243,247,0.56)"),
    "line": ("rgba(0,0,0,0.08)", "rgba(255,255,255,0.09)"),
    "line-strong": ("rgba(0,0,0,0.16)", "rgba(255,255,255,0.18)"),
    "fill": ("rgba(0,0,0,0.045)", "rgba(255,255,255,0.065)"),
    "fill-strong": ("rgba(0,0,0,0.085)", "rgba(255,255,255,0.12)"),
    "link": ("#0a6fd6", "#4ea7ff"),
    "hl-keyword": ("#4b59d6", "#7f8cff"),
    "hl-string": ("#14723a", "#6be3a0"),
    "hl-number": ("#8f5100", "#ffc466"),
    "hl-title": ("#0a6fd6", "#4ea7ff"),
    "hl-type": ("#bd2c27", "#ff8f88"),
    "hl-meta": ("#6b5d4f", "#c9bba9"),
}

FONTS = {
    "system": '-apple-system, BlinkMacSystemFont, "SF Pro Text", "SF Pro Display",'
    ' "Helvetica Neue", Helvetica, Arial, sans-serif',
    "mono": 'ui-monospace, "SF Mono", SFMono-Regular, Menlo, Monaco, Consolas, monospace',
}


def _diagram(theme: int) -> dict[str, str | bool]:
    """Mermaid's base theme in Nest's colors (light, then dark): solid hex, since Mermaid
    derives shades from them; pie slices in the accent colors.
    """

    def pick(light: str, dark: str) -> str:
        return dark if theme else light

    page, text = pick("#eeeeec", "#0c0c0d"), pick("#1a1b20", "#f2f3f7")
    box, edge = pick("#f8f8f6", "#171717"), pick("#7f7f7f", "#8c8c8c")
    slices = (
        pick("#a5573a", "#e39a78"),
        pick("#2c6a9a", "#79b4e3"),
        pick("#55702f", "#a5c26f"),
        pick("#a34a62", "#e293a9"),
        pick("#1f7a78", "#5cc4bf"),
        pick("#2b2b2e", "#e6e6e9"),
    )
    return {
        "darkMode": bool(theme),
        "fontFamily": FONTS["system"],
        "background": page,
        "primaryColor": box,
        "secondaryColor": box,
        "tertiaryColor": box,
        "primaryTextColor": text,
        "textColor": text,
        "primaryBorderColor": edge,
        "lineColor": edge,
        "pieTitleTextColor": text,
        "pieLegendTextColor": text,
        "pieSectionTextColor": pick("#ffffff", "#141416"),
        "pieStrokeColor": page,
        "pieOuterStrokeColor": page,
        **{f"pie{index}": color for index, color in enumerate(slices, start=1)},
    }


# Light and dark Mermaid variables (a test keeps them equal to design/tokens.toml).
MERMAID = (_diagram(0), _diagram(1))


def artifact_page(
    kind: ArtifactKind,
    title: str,
    content: str,
    version: int,
    storage: dict[str, str],
    files: list[FileData],
) -> str:
    """`version` is the version shown; a document's page sends it when the user saves."""
    if kind != "html":
        return templates.render(kind, title, content, version, {"storage": storage, "files": []})
    init: dict[str, object] = {
        "storage": storage,
        "files": [
            {
                "path": file.path,
                "size": len(file.data),
                "mime": file.mime,
                "data": base64.b64encode(file.data).decode(),
            }
            for file in files
        ],
    }
    return bridge.with_shim(inline(content, files), init)
