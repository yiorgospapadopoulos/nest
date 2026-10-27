import re
from pathlib import Path

import pytest

from nestd.design.css import render_css
from nestd.design.errors import DesignError
from nestd.design.loader import load_tokens
from nestd.design.models import Tokens
from tests.design_support import REPO_ROOT, minimal_tokens, write_tokens

DARK_MEDIA = '@media (prefers-color-scheme: dark) {\n  :root:not([data-theme="light"]) {\n'
DARK_EXPLICIT = ':root[data-theme="dark"] {\n'
GLASS_DARK_MEDIA = (
    '  :root:not([data-theme="light"])[data-glass="{0}"], '
    ':root:not([data-theme="light"]) [data-glass="{0}"] {{\n'
)
GLASS_DARK_EXPLICIT = (
    ':root[data-theme="dark"][data-glass="{0}"], :root[data-theme="dark"] [data-glass="{0}"] {{\n'
)


def _block(css: str, opener: str, indent: str = "") -> str:
    start = css.index(opener) + len(opener)
    return css[start : css.index(f"{indent}}}\n", start)]


def _declarations(block: str) -> dict[str, str]:
    return dict(re.findall(r"^\s*(--[a-z0-9-]+): (.+);$", block, flags=re.MULTILINE))


def test_variable_names_must_be_unique(tmp_path: Path) -> None:
    data = minimal_tokens()
    data["colors"]["status"] = {"running_fill": {"light": "#000000", "dark": "#ffffff"}}
    tokens = load_tokens(write_tokens(tmp_path, data))
    with pytest.raises(DesignError, match="--status-running-fill is defined twice"):
        render_css(tokens)


def _repository_tokens() -> Tokens:
    return load_tokens(REPO_ROOT / "design" / "tokens.toml")


def test_repository_css_is_well_formed_and_complete_in_both_themes() -> None:
    css = render_css(_repository_tokens())
    assert css == render_css(_repository_tokens())
    assert css.count("{") == css.count("}")
    light = _declarations(_block(css, ":root {\n"))
    media = _declarations(_block(css, DARK_MEDIA, "  "))
    explicit = _declarations(_block(css, DARK_EXPLICIT))
    assert media == explicit
    themed = {name for name, value in light.items() if re.match(r"#|rgba|var\(--accent", value)}
    assert themed == set(media)
    declared = set(re.findall(r"(--[a-z0-9-]+):", css))
    used = set(re.findall(r"var\((--[a-z0-9-]+)", css))
    assert used <= declared
    accents = re.findall(r':root\[data-accent="([a-z]+)"\]', css)
    assert accents == ["ocean", "teal", "moss", "clay", "rose"]
    assert re.findall(r"^\.wallpaper-([a-z]+) \{", css, flags=re.MULTILINE) == [
        "stone",
        "sage",
        "sky",
        "slate",
    ]
    glass = re.findall(r'^\[data-glass="([a-z]+)"\] \{', css, flags=re.MULTILINE)
    assert glass == ["clear", "frosted", "smoke", "bluegrey", "deep"]
    old_glass = {"--glass-border", "--glass-specular", "--glass-outline", "--glass-shadow"}
    old_glass |= {f"--glass-tint-{name}" for name in ("regular", "strong", "clear")}
    for theme in glass:
        dark = _declarations(_block(css, GLASS_DARK_EXPLICIT.format(theme)))
        assert dark == _declarations(_block(css, GLASS_DARK_MEDIA.format(theme), "  "))
        assert set(dark) == {name for name in media if name.startswith("--glass-")} - old_glass
