"""Nest's ready-made artifact pages (B88): slides, documents, designs and design systems built
from the agent's data. Every page is one document with the bridge's shim first, Nest's tokens
in both themes, pinned libraries only, and the data embedded so it cannot leave its element.
"""

import json
import re
from html.parser import HTMLParser
from importlib.resources import files
from pathlib import Path
from typing import Any

import pytest

from nestd.artifacts import templates
from nestd.artifacts.bridge import SHIM_TAG, init_tag
from nestd.artifacts.page import FONTS, LIBRARIES, MERMAID, PALETTE
from nestd.artifacts.templates import TEMPLATE_KINDS
from nestd.artifacts.templates.design_system import contrast
from nestd.artifacts.templates.shared import BOOT_TAG, EXTRA_PALETTE, LOADING, json_data
from nestd.design.loader import TOKENS_FILE, find_root, load_tokens

_DECK = "# Hello\n\nA talk\n---\n## Two\n\n- a\n- b\n---\n## Three\n"
_DOC = "Intro text.\n\n## First\n\nBody one.\n\n### Detail\n\nMore.\n\n## Second\n\nBody two.\n"
_DESIGN = json.dumps(
    {
        "intro": "Two **ideas** for the start screen.",
        "screens": [
            {
                "label": "A",
                "title": "Calm start",
                "description": "Quiet list, one *accent*.",
                "device": "phone",
                "html": "<main>A</main>",
            },
            {"label": "B", "title": "Dashboard", "device": "desktop", "html": "<main>S</main>"},
            {"label": "C", "title": "Tablet", "device": "tablet", "html": "<main>B</main>"},
        ],
    }
)
_SYSTEM = json.dumps(
    {
        "name": "Nest",
        "description": "Calm tools",
        "colors": [
            {"name": "background", "light": "#ffffff", "dark": "#000000", "role": "Page"},
            {"name": "accent", "light": "#4C6EF5", "dark": "#7B93FF"},
        ],
        "typography": [
            {"name": "Title", "family": "-apple-system, sans-serif", "size": 28, "weight": 700}
        ],
        "spacing": [{"name": "s", "value": 8}],
        "radii": [{"name": "card", "value": 16}],
        "components": [{"name": "Button", "html": "<button>Go</button>", "description": "Main"}],
    }
)
SAMPLES: dict[str, str] = {
    "markdown": "# Notes\n\nSome *text*.\n",
    "slides": _DECK,
    "document": _DOC,
    "design": _DESIGN,
    "design_system": _SYSTEM,
}
# The libraries each kind loads.
_LIBRARIES: dict[str, list[str]] = {
    "markdown": list(LIBRARIES),
    "slides": list(LIBRARIES),
    "document": list(LIBRARIES),
    "design": [LIBRARIES[0]],
    "design_system": [],
}


def render(
    kind: str, title: str, content: str, version: int = 1, init: dict[str, Any] | None = None
) -> str:
    return templates.render(kind, title, content, version, init)


class _Outline(HTMLParser):
    """Tags, the text inside elements by id, external scripts and stylesheets of a page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.scripts: list[str] = []
        self.inline: list[str] = []
        self.texts: dict[str, str] = {}
        self.attrs: dict[str, dict[str, str | None]] = {}
        self._open: list[tuple[str, str | None]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        found = dict(attrs)
        self.tags.append(tag)
        element_id = found.get("id")
        if element_id:
            self.attrs[element_id] = found
        if tag == "script" and found.get("src"):
            self.scripts.append(found["src"] or "")
        if tag in {"script", "style", "pre", "title"}:
            self._open.append((tag, element_id))
            if element_id:
                self.texts[element_id] = ""
            if tag == "script" and not found.get("src") and not found.get("type"):
                self.inline.append("")

    def handle_endtag(self, tag: str) -> None:
        if self._open and self._open[-1][0] == tag:
            self._open.pop()

    def handle_data(self, data: str) -> None:
        if not self._open:
            return
        tag, element_id = self._open[-1]
        if element_id:
            self.texts[element_id] += data
        if tag == "script" and self.inline and element_id is None:
            self.inline[-1] += data


def outline(page: str) -> _Outline:
    parsed = _Outline()
    parsed.feed(page)
    parsed.close()
    return parsed


def style_of(page: str) -> str:
    return page.split("<style>", 1)[1].split("</style>", 1)[0]


@pytest.mark.parametrize("kind", ["html", "chart", ""])
def test_only_the_four_template_kinds_render(kind: str) -> None:
    with pytest.raises(ValueError, match="no template"):
        render(kind, "T", "x")


def test_the_template_kinds() -> None:
    assert TEMPLATE_KINDS == ("markdown", "slides", "document", "design", "design_system")
    assert set(SAMPLES) == set(TEMPLATE_KINDS)


@pytest.mark.parametrize("kind", TEMPLATE_KINDS)
def test_each_page_is_one_document_with_the_shim_before_any_script(kind: str) -> None:
    page = render(kind, "Plan & <notes>", SAMPLES[kind], 2)
    head = page.split("<head>", 1)[1].split("</head>", 1)[0]
    tag = SHIM_TAG

    assert page.startswith("<!doctype html>\n<html")
    assert page.rstrip().endswith("</html>")
    assert page.count("<html") == 1
    assert '<meta charset="utf-8">' in head
    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in head
    assert '<meta name="color-scheme" content="light dark">' in head
    assert tag in head
    assert page.index(tag) == page.index("<script")
    assert "<title>Plan &amp; &lt;notes&gt;</title>" in head


@pytest.mark.parametrize("kind", TEMPLATE_KINDS)
def test_each_page_has_nests_tokens_in_both_themes_and_a_body_background(kind: str) -> None:
    style = style_of(render(kind, "T", SAMPLES[kind]))
    dark = style.split("@media (prefers-color-scheme: dark)", 1)[1].split("@media print", 1)[0]
    printed = style.split("@media print", 1)[1]

    assert "color-scheme: light dark;" in style
    for name, (light, night) in {**PALETTE, **EXTRA_PALETTE}.items():
        assert f"--nest-{name}: {light};" in style
        assert f"--nest-{name}: {night};" in dark
        # Printing uses the light colors whatever the theme.
        assert f"--nest-{name}: {light};" in printed
    assert f"--nest-font: {FONTS['system']};" in style
    assert f"--nest-mono: {FONTS['mono']};" in style
    assert re.search(r"body \{[^}]*background: var\(--nest-bg\);", style)
    assert "overflow-wrap: anywhere;" in style


@pytest.mark.parametrize("kind", TEMPLATE_KINDS)
def test_each_page_loads_only_pinned_libraries_from_allowed_hosts(kind: str) -> None:
    page = render(kind, "T", SAMPLES[kind])

    assert outline(page).scripts == _LIBRARIES[kind]
    assert "<link" not in page
    assert "url(" not in page
    assert "@import" not in page
    hosts = set(re.findall(r"https?://([^/\s\"'<>]+)", page))
    assert hosts <= {"cdn.jsdelivr.net", "cdnjs.cloudflare.com"}
    # The template's script neither navigates the frame nor touches storage or the network (the
    # shim provides storage to the page; templates keep nothing).
    script = outline(page).inline[-1]
    for word in ("location.hash", "history.", "localStorage", "fetch(", "XMLHttpRequest"):
        assert word not in script, word


@pytest.mark.parametrize("kind", TEMPLATE_KINDS)
def test_each_page_has_one_inline_script_wrapped_and_strict(kind: str) -> None:
    parsed = outline(render(kind, "T", SAMPLES[kind]))

    # The shim, the fallback timer of a page that waits for its libraries, then the template's
    # own script.
    assert len(parsed.inline) == (2 if kind == "design_system" else 3)
    script = parsed.inline[-1]
    assert script.startswith('(function () {\n"use strict";\n')
    assert script.rstrip().endswith("})();")


def _tokens_color(group: str, name: str) -> tuple[str, str]:
    tokens = load_tokens(find_root(Path(__file__).resolve()) / TOKENS_FILE)
    if group == "status.failed":
        color = tokens.status["failed"].text
    elif group.startswith("accent."):
        option = tokens.accent.options["graphite"]
        color = option.fill if group == "accent.fill" else option.on
    else:
        color = tokens.colors[group][name]
    return color.light, color.dark


def test_the_templates_extra_colors_are_nests_design_tokens() -> None:
    assert {
        "surface": _tokens_color("mac", "window_opaque"),
        "accent": _tokens_color("accent.fill", ""),
        "on-accent": _tokens_color("accent.on", ""),
        "danger": _tokens_color("status.failed", ""),
    } == EXTRA_PALETTE
    assert not set(EXTRA_PALETTE) & set(PALETTE)


def test_the_template_files_are_packaged_and_cannot_end_their_element() -> None:
    package = files("nestd.artifacts.templates")
    names = {entry.name for entry in package.iterdir()}

    assert {
        "base.css",
        "slides.css",
        "slides.js",
        "document.css",
        "document.js",
        "design.css",
        "design.js",
        "design_system.css",
        "design_system.js",
        "markdown.js",
        "common.js",
        "screens.js",
    } <= names
    for name in names:
        text = (package / name).read_text(encoding="utf-8") if "." in name else ""
        if name.endswith(".js"):
            assert "</script" not in text.lower(), name
            assert "<!--" not in text, name
        if name.endswith(".css"):
            assert "</style" not in text.lower(), name
        assert "\u2014" not in text, name


# Embedded JSON.


def test_json_is_embedded_with_markup_characters_escaped() -> None:
    data = {"html": "</script><script>alert(1)</script><!-- & \u2028\u2029 >"}

    embedded = json_data("nest-data", data)

    assert embedded.startswith('<script type="application/json" id="nest-data">')
    assert embedded.endswith("</script>")
    inner = embedded.removeprefix('<script type="application/json" id="nest-data">')
    inner = inner.removesuffix("</script>")
    for raw in ("<", ">", "&", "\u2028", "\u2029"):
        assert raw not in inner
    assert "\\u003c/script\\u003e" in inner
    assert "\\u2028\\u2029" in inner
    assert json.loads(inner) == data


# Slides.


def test_slides_keep_their_markdown_in_an_escaped_pre() -> None:
    source = (
        "# One\n</pre><script>alert(1)</script><img src=x onerror=alert(2)>\n---\n"
        '&amp; <!-- x --> <pre id="nest-md">'
    )

    page = render("slides", "Deck", source)
    parsed = outline(page)

    assert parsed.texts["nest-md"] == "\n" + source
    assert "img" not in parsed.tags
    assert parsed.tags.count("pre") == 1
    assert "&lt;/pre&gt;&lt;script&gt;" in page
    assert "&amp;amp;" in page


def test_slides_are_a_scaled_16_by_9_stage_with_a_counter_and_progress() -> None:
    page = render("slides", "Deck", _DECK)
    parsed = outline(page)
    style = style_of(page)
    script = parsed.inline[-1]

    for element in ("nest-deck", "nest-stage", "nest-count", "nest-progress", "nest-md"):
        assert element in parsed.attrs, element
    assert re.search(r"\.stage \{[^}]*width: 1280px;[^}]*height: 720px;", style)
    assert "var WIDTH = 1280;" in script
    assert "var HEIGHT = 720;" in script
    assert "Math.min(width / WIDTH, height / HEIGHT)" in script
    # Slides are split on a line that is exactly ---.
    assert 'line.replace(/\\r$/, "") === "---"' in script
    # Keys, swipes and taps on the outer thirds.
    for key in ('"ArrowRight"', '"ArrowLeft"', '"PageDown"', '"PageUp"', '" "', '"Home"', '"End"'):
        assert f"case {key}:" in script, key
    assert '"pointerup"' in script
    assert "width / 3" in script


def test_slides_print_one_per_landscape_page_without_chrome() -> None:
    style = style_of(render("slides", "Deck", _DECK))
    printed = style.split("@media print", 1)[1]

    assert "@page { size: 1280px 720px; margin: 0; }" in style
    assert "break-after: page;" in printed
    assert re.search(r"\.chrome[^{]*\{[^}]*display: none", printed)
    assert "print-color-adjust: exact;" in printed


# Document.


def test_a_document_keeps_its_markdown_in_an_escaped_pre() -> None:
    source = "## A\n</pre><script>alert(1)</script>\n&lt; stays"

    page = render("document", "Doc", source)
    parsed = outline(page)

    assert parsed.texts["nest-md"] == "\n" + source
    assert parsed.tags.count("pre") == 1
    assert "&amp;lt; stays" in page


def test_a_document_knows_its_version_for_saving() -> None:
    assert outline(render("document", "Doc", _DOC, 4)).attrs["nest-doc"]["data-version"] == "4"


def test_a_document_saves_through_the_bridge_and_edits_only_when_it_can() -> None:
    page = render("document", "Doc", _DOC)
    script = outline(page).inline[-1]

    assert SHIM_TAG in page
    assert 'typeof window.nest.saveDocument === "function"' in script
    assert "window.nest.saveDocument({ content: content, base_version: version })" in script
    assert "This document changed; reload to edit the latest version" in script
    assert 'error.code === "conflict"' in script


@pytest.mark.parametrize(
    ("content", "shown"),
    [
        (_DOC, True),
        ("# Own title\n\nText", False),
        ("\n\n  # Own title", False),
        ("#Not a heading", True),
        ("## Section first", True),
    ],
)
def test_a_document_shows_its_title_unless_the_markdown_starts_with_one(
    content: str, shown: bool
) -> None:
    page = render("document", "Report <1>", content)

    assert ('<h1 class="doc-title">Report &lt;1&gt;</h1>' in page) is shown


def test_a_document_has_contents_beside_or_above_and_prints_on_a4() -> None:
    page = render("document", "Doc", _DOC)
    parsed = outline(page)
    style = style_of(page)
    printed = style.split("@media print", 1)[1]

    assert {"nest-toc-side", "nest-toc-top"} <= set(parsed.attrs)
    assert "<summary>Contents</summary>" in page
    assert "@media (min-width: 900px)" in style
    assert "@page { size: A4 portrait;" in style
    assert re.search(r"\.toc-side,[^{]*\{[^}]*display: none", printed)
    assert ".nest-edit" in printed


# Design.


def _mockups(page: str) -> list[dict[str, str]]:
    """Each mockup's label, title, device, frame and outer size, in order."""
    found = re.findall(
        r'<article class="mockup" id="mockup-(\d+)" data-index="\d+" data-label="([^"]*)"'
        r'.*?<h2 class="mockup-title" id="[^"]*">([^<]*)</h2>'
        r'.*?<div class="device device-(\w+) frame-(\w+)" data-width="(\d+)" data-height="(\d+)"',
        page,
        re.DOTALL,
    )
    keys = ("index", "label", "title", "device", "frame", "width", "height")
    return [dict(zip(keys, values, strict=True)) for values in found]


def test_a_design_presents_each_mockup_with_its_label_title_and_description() -> None:
    page = render("design", "Start screen", _DESIGN)
    parsed = outline(page)

    assert '<p class="eyebrow">Design</p><h1>Start screen</h1>' in page
    assert '<p class="head-meta">3 mockups</p>' in page
    assert [(m["label"], m["title"]) for m in _mockups(page)] == [
        ("A", "Calm start"),
        ("B", "Dashboard"),
        ("C", "Tablet"),
    ]
    assert '<span class="badge" aria-label="Option A">A</span>' in page
    # The description's Markdown, escaped, rendered by the page; none for a mockup without.
    assert page.count('class="mockup-desc"') == 1
    assert parsed.texts["nest-desc-0"] == "\nQuiet list, one *accent*."
    # The intro first, open, labelled About.
    assert page.index('<details class="intro nest-pending" open>') < page.index('class="mockup"')
    assert "<summary>About</summary>" in page
    assert parsed.texts["nest-notes"] == "\nTwo **ideas** for the start screen."
    assert json.loads(parsed.texts["nest-data"]) == [
        "<main>A</main>",
        "<main>S</main>",
        "<main>B</main>",
    ]


def test_each_device_gets_its_real_frame() -> None:
    screens = [
        {"title": "P", "device": "phone", "html": ""},
        {"title": "T", "device": "tablet", "html": ""},
        {"title": "W", "device": "desktop", "url": "nest.app/<home>", "html": ""},
        {"title": "S", "device": "square", "html": ""},
        {"title": "M", "device": "desktop", "frame": "window", "html": ""},
        {"title": "N", "device": "desktop", "frame": "none", "html": ""},
        {"title": "Q", "device": "square", "frame": "phone", "html": ""},
        {"title": "Odd", "device": "watch", "frame": "toaster", "html": ""},
    ]
    page = render("design", "D", json.dumps({"screens": screens}))

    assert [(m["device"], m["frame"], m["width"], m["height"]) for m in _mockups(page)] == [
        ("phone", "phone", "418", "872"),
        ("tablet", "tablet", "874", "1152"),
        ("desktop", "browser", "1440", "952"),
        ("square", "none", "800", "800"),
        ("desktop", "window", "1440", "938"),
        ("desktop", "none", "1440", "900"),
        # A frame may be chosen for any device; an unknown device or frame is the default.
        ("square", "phone", "828", "828"),
        ("phone", "phone", "418", "872"),
    ]
    # The browser's address bar shows the url, else the title; the window its title.
    assert '<span class="address-text">nest.app/&lt;home&gt;</span>' in page
    assert '<span class="window-title">M</span>' in page
    assert page.count('<span class="island"></span>') == 3
    assert page.count('<span class="camera"></span>') == 1
    assert page.count('<span class="lights"><i></i><i></i><i></i></span>') == 2
    assert re.findall(r'data-screen="(\d+)" style="width: (\d+)px; height: (\d+)px;"', page)[
        :4
    ] == [
        ("0", "390", "844"),
        ("1", "834", "1112"),
        ("2", "1440", "900"),
        ("3", "800", "800"),
    ]


def test_the_old_names_still_work() -> None:
    content = json.dumps(
        {
            "notes": "Old notes",
            "screens": [
                {"title": "A", "variant": "B2", "html": ""},
                {"title": "No label", "html": ""},
                {"title": "Bad label", "label": "<x>!", "html": ""},
                {"title": "Both", "label": "Z", "variant": "Y", "html": ""},
            ],
        }
    )
    page = render("design", "D", content)

    assert outline(page).texts["nest-notes"] == "\nOld notes"
    # A missing or unusable label is the mockup's number.
    assert [m["label"] for m in _mockups(page)] == ["B2", "2", "x", "Z"]


@pytest.mark.parametrize(
    ("layout", "expected"),
    [("grid", "grid"), ("tabs", "tabs"), ("canvas", "canvas"), ("stack", "stack"), ("x", "stack")],
)
def test_the_layout_comes_from_the_data_and_can_be_switched(layout: str, expected: str) -> None:
    page = render("design", "D", json.dumps({"layout": layout, "screens": [{"title": "A"}]}))

    assert f'<body data-layout="{expected}">' in page
    for name in ("stack", "grid", "tabs", "canvas"):
        assert f'data-layout="{name}"' in page
    # A tab per mockup, labelled with its label and title.
    assert (
        '<button type="button" role="tab" id="nest-tab-0" aria-controls="mockup-0"'
        ' aria-selected="false" tabindex="-1"><span class="badge">1</span> A</button>'
    ) in page


def test_a_design_has_an_overlay_and_canvas_zoom_tools() -> None:
    page = render("design", "D", _DESIGN)
    parsed = outline(page)
    script = parsed.inline[-1]

    assert {"nest-canvas", "nest-world", "nest-zoom", "nest-viewer"} <= set(parsed.attrs)
    assert parsed.attrs["nest-viewer"]["role"] == "dialog"
    assert parsed.attrs["nest-viewer"]["aria-modal"] == "true"
    for zoom in ("in", "out", "fit"):
        assert f'data-zoom="{zoom}"' in page
    for event in ('"wheel"', '"pointerdown"', '"pointermove"', '"gesturechange"', '"keydown"'):
        assert event in script, event
    assert 'role="button" tabindex="0" aria-label="Open A, Calm start, larger"' in page


def test_a_design_embeds_each_screens_html_as_json_by_index() -> None:
    html = "<style>:root{--x:1}</style></script><script>alert(1)</script>"
    content = json.dumps({"screens": [{"title": "A", "device": "phone", "html": html}]})

    page = render("design", "D", content)
    parsed = outline(page)

    assert json.loads(parsed.texts["nest-data"]) == [html]
    assert "alert(1)</script>" not in page
    # The shim, the fallback timer, marked, the data and the template's script.
    assert parsed.tags.count("script") == 5


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("not json", "This design could not be read."),
        ("[1, 2]", "This design could not be read."),
        ('{"screens": "x"}', "This design has no screens."),
        ('{"screens": [1, "x", null]}', "This design has no screens."),
    ],
)
def test_a_design_that_cannot_be_read_says_so(content: str, message: str) -> None:
    page = render("design", "D", content)

    assert f'<p class="empty">{message}</p>' in page
    assert json.loads(outline(page).texts["nest-data"]) == []


def test_a_design_reads_odd_screens_defensively() -> None:
    content = json.dumps(
        {
            "screens": [
                {"device": "watch", "html": 5, "label": 3, "description": 4},
                {"title": "\ud800 <b>", "label": "B", "device": "tablet", "url": 7},
            ],
            "intro": 7,
            "layout": 3,
        }
    )

    page = render("design", "D", content)
    parsed = outline(page)

    assert [(m["label"], m["title"]) for m in _mockups(page)] == [
        ("1", "Screen 1"),
        ("B", "� &lt;b&gt;"),
    ]
    assert json.loads(parsed.texts["nest-data"]) == ["", ""]
    assert "nest-notes" not in parsed.attrs
    assert 'class="mockup-desc"' not in page
    assert '<body data-layout="stack">' in page
    page.encode("utf-8")


def test_contrast_follows_wcag() -> None:
    assert contrast("#000000", "#ffffff") == pytest.approx(21)
    assert contrast("#fff", "#fff") == pytest.approx(1)
    assert contrast("#767676", "#ffffff") == pytest.approx(4.54, abs=0.01)
    # A translucent color is laid over the background first.
    assert contrast("#00000000", "#ffffff") == pytest.approx(1)
    assert contrast("#00000080", "#ffffff") == pytest.approx(contrast("#7f7f7f", "#ffffff"), 0.02)


def _swatches(page: str) -> list[tuple[str, str]]:
    return re.findall(r'<span class="hex">([^<]*)</span><span class="ratio">([^<]*)</span>', page)


def test_a_design_system_shows_each_color_in_light_and_dark_with_its_contrast() -> None:
    page = render("design_system", "System", _SYSTEM)

    assert "<h1>Nest</h1>" in page
    assert '<p class="desc">Calm tools</p>' in page
    assert re.findall(r'<strong class="swatch-name">([^<]*)</strong>', page) == [
        "background",
        "accent",
    ]
    assert '<span class="role">Page</span>' in page
    # Against the system's own background; the background itself has no ratio.
    assert _swatches(page) == [
        ("Light #ffffff", "Background"),
        ("Dark #000000", "Background"),
        ("Light #4C6EF5", "4.3:1 AA large"),
        ("Dark #7B93FF", "7.4:1 AAA"),
    ]


def test_without_a_background_colors_are_measured_against_white_and_black() -> None:
    system = {
        "name": "S",
        "colors": [
            {"name": "ink", "light": "#000", "dark": "#fff"},
            {"name": "faint", "light": "#eeeeee"},
        ],
    }
    page = render("design_system", "S", json.dumps(system))

    # No dark value: the light one is shown on the dark background too.
    assert _swatches(page) == [
        ("Light #000", "21:1 AAA"),
        ("Dark #fff", "21:1 AAA"),
        ("Light #eeeeee", "1.1:1 Low"),
        ("Dark same as light", "18:1 AAA"),
    ]
    # Previews of components sit on white and black too.
    assert ".preview { background: #ffffff; }" in page
    assert ".preview { background: #000000; }" in page


def test_a_named_page_color_is_the_background_when_there_is_no_background() -> None:
    system = {
        "colors": [
            {"name": "Page", "light": "#ffffff"},
            {"name": "text", "light": "#777777", "dark": "#777777"},
        ]
    }
    page = render("design_system", "Fallback title", json.dumps(system))

    assert "<h1>Fallback title</h1>" in page
    assert _swatches(page)[2:] == [
        ("Light #777777", "4.4:1 AA large"),
        ("Dark #777777", "4.6:1 AA"),
    ]


def test_a_design_system_skips_colors_that_are_not_hex() -> None:
    system = {
        "colors": [
            {"name": "bad", "light": "red"},
            {"name": "worse", "light": "#12345"},
            {"name": "evil", "light": "#fff;background:url(x)"},
            {"name": "dark bad", "light": "#ffffff", "dark": "blue"},
            "not a color",
            {"light": "#abcdef"},
        ]
    }
    page = render("design_system", "S", json.dumps(system))

    assert re.findall(r'<strong class="swatch-name">([^<]*)</strong>', page) == [
        "dark bad",
        "Color 5",
    ]
    assert "url(" not in page
    assert ("Dark same as light", "1:1 Low") not in _swatches(page)
    assert ("Dark same as light", "21:1 AAA") in _swatches(page)


def test_a_design_system_shows_its_type_scale_safely() -> None:
    system = {
        "typography": [
            {"name": "Title", "family": "Inter; } body { x: url(y)", "size": 28, "weight": 700},
            {"name": "Body", "family": '"SF Pro", Arial', "size": 16, "line_height": 1.5},
            {"name": "Tall", "size": 16, "line_height": 24, "sample": "Hi <b>"},
            {"name": "Odd", "size": "big", "weight": True, "line_height": -1, "family": 3},
            {"size": 10000, "weight": 5000},
        ]
    }
    page = render("design_system", "S", json.dumps(system))
    styles = re.findall(r'<p class="type-sample" style="([^"]*)">([^<]*)</p>', page)

    assert styles == [
        ("font-family: Inter body x urly; font-size: 28px; font-weight: 700;", "Title"),
        (
            "font-family: &quot;SF Pro&quot;, Arial; font-size: 16px; font-weight: 400;"
            " line-height: 1.5;",
            "Body",
        ),
        ("font-size: 16px; font-weight: 400; line-height: 24px;", "Hi &lt;b&gt;"),
        ("font-size: 16px; font-weight: 400;", "Odd"),
        ("font-size: 16px; font-weight: 400;", "Style 5"),
    ]
    assert re.findall(r'<span class="type-size">([^<]*)</span>', page) == [
        "28 px, 700",
        "16 px / 1.5, 400",
        "16 px / 24 px, 400",
        "16 px, 400",
        "16 px, 400",
    ]


def test_a_design_system_shows_spacing_and_radii_as_bars_and_tiles() -> None:
    system = {
        "spacing": [{"name": "s", "value": 8}, {"name": "l", "value": 2.5}, {"value": "x"}],
        "radii": [{"name": "card", "value": 16}, {"name": "pill", "value": 999}],
    }
    page = render("design_system", "S", json.dumps(system))

    assert re.findall(r'<span class="bar" style="width: ([^"]*)px;"></span>', page) == [
        "8",
        "2.5",
        "0",
    ]
    assert re.findall(r'<span class="tile" style="border-radius: ([^"]*)px;"></span>', page) == [
        "16",
        "999",
    ]
    assert "<h2>Spacing</h2>" in page
    assert "<h2>Radii</h2>" in page
    for missing in ("Colors", "Typography", "Components"):
        assert f"<h2>{missing}</h2>" not in page


def test_a_design_system_embeds_components_as_json_with_a_preview_each() -> None:
    page = render("design_system", "S", _SYSTEM)
    parsed = outline(page)

    assert json.loads(parsed.texts["nest-data"]) == ["<button>Go</button>"]
    assert '<div class="preview" data-component="0"></div>' in page
    assert "<strong>Button</strong>" in page
    assert '<span class="component-desc">Main</span>' in page


@pytest.mark.parametrize("content", ["nope", "[]", "{}", '{"colors": 5, "components": [1]}'])
def test_a_design_system_that_is_empty_or_unreadable_still_renders(content: str) -> None:
    page = render("design_system", "Empty", content)

    assert "<h1>Empty</h1>" in page
    assert '<p class="empty">This design system has nothing to show yet.</p>' in page
    assert json.loads(outline(page).texts["nest-data"]) == []


def test_mermaid_colors_are_shared_with_markdown_pages() -> None:
    for kind in ("slides", "document"):
        assert json.dumps(list(MERMAID)) in render(kind, "T", SAMPLES[kind])


# Nothing half built shows: no Markdown source before it is rendered, no unfitted layout.

_PENDING = {
    "markdown": [],
    "slides": [
        '<main id="nest-deck" class="deck nest-pending"',
        '<div class="chrome nest-pending">',
    ],
    "document": ['<div id="nest-doc" class="doc-layout nest-pending"'],
    "design": [
        '<details class="intro nest-pending" open>',
        '<main id="nest-canvas" class="mockups nest-pending"',
    ],
}


@pytest.mark.parametrize("kind", ["markdown", "slides", "document", "design"])
def test_pages_that_render_markdown_show_nothing_half_built(kind: str) -> None:
    page = render(kind, "T", SAMPLES[kind])
    head = page.split("<head>", 1)[1].split("</head>", 1)[0]
    style = style_of(page)
    script = outline(page).inline[-1]

    assert "html:not(.nest-ready):not(.nest-fallback) #nest-md { display: none; }" in style
    assert "html:not(.nest-ready):not(.nest-fallback) .nest-pending" in style
    assert "visibility: hidden; opacity: 0;" in style
    for marked in _PENDING[kind]:
        assert marked in page, marked
    # The ring shows only after 150 ms, never spins under reduced motion, and goes when ready.
    assert page.split("<body", 1)[1].split(">", 1)[1].lstrip().startswith(LOADING)
    assert "animation: nest-appear 0.2s ease 0.15s forwards;" in style
    assert (
        "html.nest-ready .nest-loading, html.nest-fallback .nest-loading { display: none; }"
        in style
    )
    reduced = style.split("@media (prefers-reduced-motion: reduce)", 1)[1].split("\n}\n", 1)[0]
    assert ".nest-loading { animation: nest-appear 0s linear 0.15s forwards; }" in reduced
    assert ".nest-loading span { animation: none; }" in reduced
    # The libraries' fallback after 6 s, set before they can block the page.
    assert head.index(SHIM_TAG) < head.index(BOOT_TAG)
    assert page.index(BOOT_TAG) < page.index("<script src=")
    # The script marks the page started, then ready; a failure shows the fallback.
    assert script.index('classList.add("nest-started")') < script.index("try {")
    assert 'classList.add("nest-ready")' in script
    assert '} catch (error) {\n  document.documentElement.classList.add("nest-fallback");' in script


def test_the_design_system_has_nothing_to_wait_for() -> None:
    page = render("design_system", "S", _SYSTEM)

    assert BOOT_TAG not in page
    assert LOADING not in page
    assert "nest-pending" not in page


# Stage 3: every page gets its init data (what it stored) right before the shim.


@pytest.mark.parametrize("kind", TEMPLATE_KINDS)
def test_each_page_carries_its_init_data_right_before_the_shim(kind: str) -> None:
    init: dict[str, Any] = {"storage": {"note": "</script><script>alert(1)</script>"}, "files": []}
    page = render(kind, "T", SAMPLES[kind], 1, init)
    head = page.split("<head>", 1)[1].split("</head>", 1)[0]

    assert init_tag(init) + SHIM_TAG in head
    assert page.index(init_tag(init)) < page.index("<script>")
    assert json.loads(outline(page).texts["nest-init"]) == init
    assert "</script><script>alert(1)" not in page
    # Without init data, no element.
    assert 'id="nest-init"' not in render(kind, "T", SAMPLES[kind])


# The plain Markdown kind.


def test_markdown_keeps_its_source_in_an_escaped_pre() -> None:
    source = "</pre><script>alert(1)</script><img src=x onerror=alert(2)>\n&amp; stays"

    page = render("markdown", "Notes & <more>", source)
    parsed = outline(page)

    assert parsed.texts["nest-md"] == "\n" + source
    assert "img" not in parsed.tags
    assert parsed.tags.count("pre") == 1
    assert "<title>Notes &amp; &lt;more&gt;</title>" in page
    assert "&amp;amp; stays" in page


def test_markdown_is_rendered_cleaned_with_its_diagrams_drawn_when_shown() -> None:
    script = outline(render("markdown", "T", "# x")).inline[-1]

    assert "markdown(source.textContent)" in script
    assert "clean(html, MARKDOWN)" in script
    assert "drawDiagrams(doc)" in script
    assert "onResize(document.documentElement" in script
    assert "markReady();" in script
    assert 'classList.add("nest-fallback")' in script
