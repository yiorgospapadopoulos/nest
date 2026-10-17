"""The page a client shows in its sandbox (B82): an HTML artifact as saved, a Markdown one in
a Nest-styled document that renders it with pinned libraries and stays readable without them.
"""

import json
import re
from html.parser import HTMLParser
from pathlib import Path

from nestd.artifacts.page import FONTS, LIBRARIES, MERMAID, PALETTE, artifact_page
from nestd.design.loader import TOKENS_FILE, find_root, load_tokens
from nestd.design.models import ThemedColor, Tokens


class _Outline(HTMLParser):
    """The tags of a document, the text of its `<title>` and `<pre id="nest-md">`, and the
    external scripts it loads.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.scripts: list[str] = []
        self.title = ""
        self.source = ""
        self._open: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        found = dict(attrs)
        if tag == "script" and found.get("src"):
            self.scripts.append(found["src"] or "")
        if tag == "title" or (tag == "pre" and found.get("id") == "nest-md"):
            self._open = tag

    def handle_endtag(self, tag: str) -> None:
        if tag == self._open:
            self._open = None

    def handle_data(self, data: str) -> None:
        if self._open == "title":
            self.title += data
        elif self._open == "pre":
            self.source += data


def outline(page: str) -> _Outline:
    parsed = _Outline()
    parsed.feed(page)
    parsed.close()
    return parsed


def test_an_html_page_is_shown_as_saved() -> None:
    page = "<html><body><script>alert(1)</script></body></html>"

    assert artifact_page("html", "Chart", page) == page


def test_markdown_is_a_whole_document_with_its_title() -> None:
    page = artifact_page("markdown", "Plan & <notes>", "# Plan\n")

    assert page.startswith("<!doctype html>\n<html")
    assert '<meta charset="utf-8">' in page
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in page
    assert '<meta name="color-scheme" content="light dark">' in page
    assert "<title>Plan &amp; &lt;notes&gt;</title>" in page
    assert outline(page).title == "Plan & <notes>"


def test_markdown_that_looks_like_html_cannot_leave_its_pre() -> None:
    source = (
        "</pre><script>alert(1)</script><img src=x onerror=alert(2)>\n"
        '&amp; stays &amp;\n<!-- not a comment --> ]]> <pre id="nest-md">'
    )

    page = artifact_page("markdown", "Tricky", source)
    parsed = outline(page)

    # The parser reads the source back exactly, and no tag in it became an element.
    assert parsed.source == "\n" + source
    assert "img" not in parsed.tags
    assert parsed.tags.count("pre") == 1
    assert parsed.tags.count("script") == len(LIBRARIES) + 1
    assert "&lt;/pre&gt;&lt;script&gt;" in page
    assert "&amp;amp; stays" in page


def test_a_leading_newline_of_the_source_is_kept() -> None:
    # The parser drops one newline right after <pre>; the page adds its own.
    assert outline(artifact_page("markdown", "T", "\n\nText")).source == "\n\n\nText"
    assert '<pre id="nest-md">\n\n\nText</pre>' in artifact_page("markdown", "T", "\n\nText")


def test_markdown_renders_with_pinned_libraries_from_allowed_hosts() -> None:
    page = artifact_page("markdown", "T", "x")

    assert outline(page).scripts == [
        "https://cdn.jsdelivr.net/npm/marked@12.0.2/marked.min.js",
        "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js",
        "https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js",
    ]
    assert outline(page).scripts == list(LIBRARIES)
    # No stylesheet, font or image is fetched: highlight colors are inline.
    assert "<link" not in page
    assert "url(" not in page


def test_the_renderer_reads_the_text_and_keeps_it_readable_without_the_libraries() -> None:
    page = artifact_page("markdown", "T", "x")
    script = page.rsplit("<script>", 1)[1]

    assert 'document.getElementById("nest-md")' in script
    assert ".textContent" in script
    # Without marked (offline, or a blocked script) the source stays shown as it is.
    assert "if (!window.marked) return;" in script
    assert "gfm: true" in script
    # Mermaid blocks become diagrams in the theme the page is shown in; other code is
    # highlighted when highlight.js knows the language.
    assert 'lang === "mermaid"' in script
    assert 'DIAGRAMS[window.matchMedia("(prefers-color-scheme: dark)").matches ? 1 : 0]' in script
    assert 'securityLevel: "strict"' in script
    assert "hljs.getLanguage(lang)" in script
    # Mermaid or highlight.js missing leaves plain code blocks.
    assert "window.mermaid" in script
    assert "window.hljs" in script


def test_the_page_fits_a_phone_and_has_both_themes() -> None:
    page = artifact_page("markdown", "T", "x")
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]

    assert re.search(r"body \{[^}]*background: var\(--nest-bg\);", style)
    assert "@media (prefers-color-scheme: dark)" in style
    # Wide tables and code scroll inside themselves, never the page.
    assert re.search(r"table \{[^}]*overflow-x: auto;", style)
    assert re.search(r"pre \{[^}]*overflow-x: auto;", style)
    assert "overflow-wrap: anywhere;" in style
    assert re.search(r"img,\s*svg \{[^}]*max-width: 100%;", style)
    # The offline fallback wraps long lines.
    assert re.search(r"#nest-md \{[^}]*white-space: pre-wrap;", style)
    assert re.search(r"#nest-md \{[^}]*overflow-wrap: anywhere;", style)
    for name, (light, dark) in PALETTE.items():
        assert f"--nest-{name}: {light};" in style
        assert f"--nest-{name}: {dark};" in style


# The design token each color of the page comes from.
_TOKENS: dict[str, tuple[str, str]] = {
    "bg": ("page", "base"),
    "text": ("text", "primary"),
    "text-2": ("text", "secondary"),
    "text-3": ("text", "tertiary"),
    "line": ("line", "hairline"),
    "line-strong": ("line", "strong"),
    "fill": ("fill", "subtle"),
    "fill-strong": ("fill", "strong"),
    "link": ("mac", "link"),
    "hl-keyword": ("mac", "run"),
    "hl-string": ("diff", "added_text"),
    "hl-number": ("status.waiting", "text"),
    "hl-title": ("mac", "link"),
    "hl-type": ("status.failed", "text"),
    "hl-meta": ("status.interrupted", "text"),
}


def _tokens() -> Tokens:
    return load_tokens(find_root(Path(__file__).resolve()) / TOKENS_FILE)


def _token(group: str, name: str) -> ThemedColor:
    tokens = _tokens()
    if group.startswith("status."):
        return getattr(tokens.status[group.removeprefix("status.")], name)
    return tokens.colors[group][name]


def test_the_colors_are_nests_design_tokens() -> None:
    assert set(PALETTE) == set(_TOKENS)
    for name, (group, token) in _TOKENS.items():
        color = _token(group, token)
        assert PALETTE[name] == (color.light, color.dark), name


def test_the_fonts_are_nests_font_stacks() -> None:
    families = _tokens().typography.family
    for name, stack in FONTS.items():
        quoted = (f'"{family}"' if " " in family else family for family in families[name])
        assert stack == ", ".join(quoted)
        assert stack in artifact_page("markdown", "T", "x")


# Mermaid's variables, by name: where each comes from in the tokens (group, token).
_MERMAID_TOKENS: dict[str, tuple[str, str]] = {
    "background": ("page", "base"),
    "primaryColor": ("mac", "window_opaque"),
    "secondaryColor": ("mac", "window_opaque"),
    "tertiaryColor": ("mac", "window_opaque"),
    "primaryTextColor": ("text", "primary"),
    "textColor": ("text", "primary"),
    "primaryBorderColor": ("mac", "text_secondary"),
    "lineColor": ("mac", "text_secondary"),
    "pieTitleTextColor": ("text", "primary"),
    "pieLegendTextColor": ("text", "primary"),
    "pieStrokeColor": ("page", "base"),
    "pieOuterStrokeColor": ("page", "base"),
}
_PIE_ACCENTS = ("clay", "ocean", "moss", "rose", "teal", "graphite")


def test_diagrams_take_nests_colors_in_both_themes() -> None:
    tokens = _tokens()
    for theme, variables in enumerate(MERMAID):

        def pick(color: ThemedColor, theme: int = theme) -> str:
            return color.dark if theme else color.light

        assert variables["darkMode"] is bool(theme)
        assert variables["fontFamily"] == FONTS["system"]
        for name, (group, token) in _MERMAID_TOKENS.items():
            assert variables[name] == pick(tokens.colors[group][token]), name
        for index, accent in enumerate(_PIE_ACCENTS, start=1):
            option = tokens.accent.options[accent]
            assert variables[f"pie{index}"] == pick(option.fill), accent
            assert variables["pieSectionTextColor"] == pick(option.on)
        # Mermaid derives colors from these, so they must be plain hex, not rgba.
        for name, value in variables.items():
            if isinstance(value, str) and name != "fontFamily":
                assert re.fullmatch(r"#[0-9a-f]{6}", value), name


def test_diagrams_use_the_base_theme_with_the_page_theme_s_variables() -> None:
    page = artifact_page("markdown", "T", "x")
    assert 'theme: "base"' in page
    assert "themeVariables: diagram" in page
    assert json.dumps(list(MERMAID)) in page
