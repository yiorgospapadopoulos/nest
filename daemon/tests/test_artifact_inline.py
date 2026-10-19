"""A multi-file page made one document (B88 stage 3): scripts, stylesheets, images and CSS
urls that name the page's own files by a relative path are inlined; everything else is
left as the agent wrote it.
"""

import base64

import pytest

from nestd.artifacts.files import FileData
from nestd.artifacts.inline import inline

LOGO = b"\x89PNG\r\n"
LOGO_URI = "data:image/png;base64," + base64.b64encode(LOGO).decode()
FILES = [
    FileData("app.js", b"start()", "text/javascript"),
    FileData("lib/chart.js", b"draw()", "text/javascript"),
    FileData("css/style.css", b"body{background:url(../img/logo.png)}", "text/css"),
    FileData("img/logo.png", LOGO, "image/png"),
    FileData("fonts/a.woff2", b"wOF2", "font/woff2"),
]


def test_without_files_the_page_is_unchanged() -> None:
    page = '<script src="app.js"></script>'

    assert inline(page, []) is page


@pytest.mark.parametrize(
    ("page", "expected"),
    [
        ('<script src="app.js"></script>', "<script>start()</script>"),
        ("<SCRIPT SRC=app.js></SCRIPT>", "<script>start()</script>"),
        ("<script src='./lib/chart.js' defer></script>", "<script defer>draw()</script>"),
        (
            '<script type="module" src="app.js?v=2"></script>',
            '<script type="module">start()</script>',
        ),
        ('<script src="app.js">\n</script >', "<script>start()</script>"),
    ],
)
def test_scripts_naming_a_file_get_its_text(page: str, expected: str) -> None:
    assert inline(page, FILES) == expected


def test_a_scripts_text_cannot_end_its_element() -> None:
    files = [FileData("app.js", b"a('</script>'); b('<!-- <script>'); c('</SCRIPT x')", "x")]

    shown = inline('<script src="app.js"></script>', files)

    assert shown == ("<script>a('<\\/script>'); b('<\\!-- <script>'); c('<\\/SCRIPT x')</script>")


def test_a_stylesheet_becomes_a_style_with_its_urls_inlined() -> None:
    shown = inline('<link rel="stylesheet" href="css/style.css">', FILES)

    assert shown == f'<style>body{{background:url("{LOGO_URI}")}}</style>'


def test_a_stylesheets_text_cannot_end_its_element() -> None:
    files = [FileData("a.css", b"p::after{content:'</style>'}", "text/css")]

    assert inline("<link href=a.css rel=stylesheet />", files) == (
        "<style>p::after{content:'<\\/style>'}</style>"
    )


def test_images_and_css_urls_become_data_uris() -> None:
    page = (
        '<img src="img/logo.png" alt="Logo">'
        "<div style=\"background: url('img/logo.png')\"></div>"
        "<style>@font-face{src:url(fonts/a.woff2)}</style>"
    )

    shown = inline(page, FILES)

    assert shown == (
        f'<img src="{LOGO_URI}" alt="Logo">'
        f'<div style="background: url(&quot;{LOGO_URI}&quot;)"></div>'
        '<style>@font-face{src:url("data:font/woff2;base64,'
        + base64.b64encode(b"wOF2").decode()
        + '")}</style>'
    )


@pytest.mark.parametrize(
    "page",
    [
        '<script src="https://cdn.jsdelivr.net/npm/x@1/x.js"></script>',
        '<script src="//cdn.example/x.js"></script>',
        '<script src="/app.js"></script>',
        '<script src="missing.js"></script>',
        '<script src="../app.js"></script>',
        "<script>el.innerHTML = '<img src=\"img/logo.png\">';</script>",
        '<!-- <img src="img/logo.png"> -->',
        '<link rel="icon" href="img/logo.png">',
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter">',
        '<img src="data:image/png;base64,AAAA">',
        '<img alt="no source">',
        '<div style="color: red"></div>',
        "<style>.a{background:url(#grad)} .b{background:url(missing.png)}</style>",
        '<a href="app.js">app</a>',
        "<p>2 < 3 and 4 > 1</p>",
    ],
)
def test_other_references_are_left_alone(page: str) -> None:
    assert inline(page, FILES) == page


def test_attributes_keep_their_values_when_a_tag_is_rewritten() -> None:
    page = '<img data-x=\'a"b\' src=img/logo.png hidden title="T &amp; U" />'

    assert inline(page, FILES) == (
        f'<img data-x="a&quot;b" src="{LOGO_URI}" hidden title="T &amp; U" />'
    )
