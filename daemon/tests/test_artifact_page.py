"""The page a client shows in its sandbox for a version (B82, B88): an HTML artifact with its
files inlined, every other kind built by Nest's templates; each with the shim and what the
page stored. The colors, fonts and diagram colors the templates use are Nest's design tokens.
"""

import base64
import re
from pathlib import Path

import pytest

from nestd.artifacts import bridge, templates
from nestd.artifacts.files import FileData
from nestd.artifacts.models import ArtifactKind
from nestd.artifacts.page import FONTS, MERMAID, PALETTE, artifact_page
from nestd.design.loader import TOKENS_FILE, find_root, load_tokens
from nestd.design.models import ThemedColor, Tokens

type Init = dict[str, object]

STORED = {"habits": '["read"]'}


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...] | tuple[object, ...]]:
    """The calls to the templates and the shim, which answer with markers."""
    calls: list[tuple[object, ...]] = []

    def render(kind: str, title: str, content: str, version: int, init: Init) -> str:
        calls.append(("render", kind, title, content, version, init))
        return "<built>"

    def with_shim(document: str, init: Init) -> str:
        calls.append(("shim", document, init))
        return "<shimmed>" + document

    monkeypatch.setattr(templates, "render", render)
    monkeypatch.setattr(bridge, "with_shim", with_shim)
    return calls


@pytest.mark.parametrize("kind", ["markdown", "slides", "document", "design", "design_system"])
def test_every_kind_but_html_is_built_by_its_template_with_what_the_page_stored(
    built: list[tuple[object, ...]], kind: ArtifactKind
) -> None:
    page = artifact_page(kind, "Deck", "# One", 3, STORED, [])

    assert page == "<built>"
    assert built == [("render", kind, "Deck", "# One", 3, {"storage": STORED, "files": []})]


def test_an_html_page_gets_the_shim_with_its_storage_and_files(
    built: list[tuple[object, ...]],
) -> None:
    files = [FileData("data.json", b"[1]", "application/json")]
    page = "<!doctype html><p>x</p>"

    shown = artifact_page("html", "Chart", page, 2, STORED, files)

    assert shown == "<shimmed>" + page
    assert built == [
        (
            "shim",
            page,
            {
                "storage": STORED,
                "files": [
                    {
                        "path": "data.json",
                        "size": 3,
                        "mime": "application/json",
                        "data": base64.b64encode(b"[1]").decode(),
                    }
                ],
            },
        )
    ]


def test_an_html_page_has_its_files_inlined_before_the_shim(
    built: list[tuple[object, ...]],
) -> None:
    files = [FileData("app.js", b"start()", "text/javascript")]

    artifact_page("html", "App", '<script src="app.js"></script>', 1, {}, files)

    assert built[0][1] == "<script>start()</script>"


def test_the_real_shim_and_templates_take_the_init_data() -> None:
    files = [FileData("app.js", b"start()", "text/javascript")]

    html = artifact_page("html", "App", '<script src="app.js"></script>', 1, STORED, files)
    markdown = artifact_page("markdown", "Notes", "# Notes", 1, STORED, [])

    for page in (html, markdown):
        assert bridge.SHIM_TAG in page
        assert 'id="nest-init"' in page
        assert "habits" in page
    assert "<script>start()</script>" in html


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
