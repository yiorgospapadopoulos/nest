"""Design systems: the agent's tokens and components on one page. Colors show in light and
dark side by side with their hex and WCAG contrast against the system's background (a color
named `background`, else `page`, else white and black); then the type scale, spacing and
radius bars, and each component in its own shadow root like a design's screens. Everything
but the components is laid out here; only checked hex colors and numbers reach the styles.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape
from typing import Any

from nestd.artifacts.templates.shared import (
    figure,
    items,
    json_data,
    number,
    page,
    parse,
    resource,
    script,
    text,
)

_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
# What a font family may hold: names, quotes, commas, dashes and dots, never CSS syntax.
_NOT_FAMILY = re.compile(r"[^\w\s,'\"\-.]")
_SAMPLE = "The quick brown fox jumps over the lazy dog"
# Readable text on a light or a dark background (Nest's text tokens).
_INK = ("#1a1b20", "#f2f3f7")

type _Rgb = tuple[float, float, float]


def _rgba(color: str) -> tuple[float, float, float, float]:
    digits = color[1:]
    if len(digits) == 3:
        digits = "".join(digit * 2 for digit in digits)
    red, green, blue = (int(digits[at : at + 2], 16) / 255 for at in (0, 2, 4))
    alpha = int(digits[6:8], 16) / 255 if len(digits) == 8 else 1.0
    return red, green, blue, alpha


def _over(color: str, below: _Rgb) -> _Rgb:
    red, green, blue, alpha = _rgba(color)
    return (
        red * alpha + below[0] * (1 - alpha),
        green * alpha + below[1] * (1 - alpha),
        blue * alpha + below[2] * (1 - alpha),
    )


def _luminance(rgb: _Rgb) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (channel(value) for value in rgb)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(color: str, background: str, base: str = "#ffffff") -> float:
    """WCAG contrast of a hex color laid over a background, itself laid over `base`."""
    below = _over(background, _over(base, (0.0, 0.0, 0.0)))
    lighter, darker = sorted((_luminance(_over(color, below)), _luminance(below)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _grade(ratio: float) -> str:
    shown = figure(math.floor(ratio * 10) / 10)
    if ratio >= 7:
        return f"{shown}:1 AAA"
    if ratio >= 4.5:
        return f"{shown}:1 AA"
    if ratio >= 3:
        return f"{shown}:1 AA large"
    return f"{shown}:1 Low"


def _hex(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    return value if isinstance(value, str) and _HEX.fullmatch(value) else None


@dataclass(frozen=True)
class _Color:
    name: str
    light: str
    dark: str | None
    role: str


def _colors(data: dict[str, Any] | None) -> list[_Color]:
    found: list[_Color] = []
    for index, item in enumerate(items(data, "colors")):
        light = _hex(item, "light")
        if light is not None:
            name = text(item, "name") or f"Color {index + 1}"
            found.append(_Color(name, light, _hex(item, "dark"), text(item, "role")))
    return found


def _background(colors: list[_Color]) -> _Color | None:
    for wanted in ("background", "page"):
        for color in colors:
            if color.name.strip().lower() == wanted:
                return color
    return None


def _mode(color: _Color, dark: bool, background: _Color | None) -> str:
    base = "#000000" if dark else "#ffffff"
    if dark:
        value = color.dark or color.light
        behind = (background.dark if background else None) or base
    else:
        value = color.light
        behind = background.light if background else base
    ink = _INK[_luminance(_over(behind, _over(base, (0.0, 0.0, 0.0)))) < 0.4]
    hex_label = "same as light" if dark and color.dark is None else value
    ratio = "Background" if color is background else _grade(contrast(value, behind, base))
    return (
        f'<div class="mode" style="background: {behind}; color: {ink};">'
        f'<span class="chip" style="--chip: {value};"></span>'
        f'<span class="sample" style="color: {value};">Aa</span>'
        f'<span class="hex">{"Dark" if dark else "Light"} {hex_label}</span>'
        f'<span class="ratio">{ratio}</span></div>'
    )


def _swatch(color: _Color, background: _Color | None) -> str:
    role = f'<span class="role">{escape(color.role)}</span>' if color.role else ""
    return (
        '<article class="swatch"><div class="swatch-head">'
        f'<strong class="swatch-name">{escape(color.name)}</strong>{role}</div>'
        f'<div class="modes">{_mode(color, False, background)}'
        f"{_mode(color, True, background)}</div></article>"
    )


def _type(index: int, item: dict[str, Any]) -> str:
    name = text(item, "name") or f"Style {index + 1}"
    family = " ".join(_NOT_FAMILY.sub("", text(item, "family")).split())[:300]
    size = number(item, "size", 1, 512) or 16
    weight = number(item, "weight", 1, 1000)
    weight_text = figure(round(weight)) if weight is not None else "400"
    height = number(item, "line_height", 0.1, 400)
    # A line height above 4 is in pixels, below it a multiple of the size.
    height_css = None if height is None else figure(height) + ("px" if height > 4 else "")
    styles = [f"font-family: {family};"] if family else []
    styles += [f"font-size: {figure(size)}px;", f"font-weight: {weight_text};"]
    if height_css is not None:
        styles.append(f"line-height: {height_css};")
    measure = f"{figure(size)} px" + (f" / {height_css.replace('px', ' px')}" if height_css else "")
    family_line = f'<span class="family">{escape(family)}</span>' if family else ""
    return (
        '<div class="type-row"><div class="type-meta">'
        f'<strong>{escape(name)}</strong><span class="type-size">{measure}, {weight_text}</span>'
        f"{family_line}</div>"
        f'<p class="type-sample" style="{escape(" ".join(styles))}">'
        f"{escape(text(item, 'sample') or name)}</p></div>"
    )


def _measure(index: int, item: dict[str, Any], label: str) -> tuple[str, str]:
    value = number(item, "value", 0, 10000) or 0.0
    return escape(text(item, "name") or f"{label} {index + 1}"), figure(value)


def _space(index: int, item: dict[str, Any]) -> str:
    name, value = _measure(index, item, "Space")
    return (
        f'<div class="space-row"><span class="space-name">{name}</span>'
        f'<span class="value">{value}</span>'
        f'<span class="bar" style="width: {value}px;"></span></div>'
    )


def _radius(index: int, item: dict[str, Any]) -> str:
    name, value = _measure(index, item, "Radius")
    return (
        f'<div class="radius"><span class="tile" style="border-radius: {value}px;"></span>'
        f'<span class="radius-name">{name}</span><span class="value">{value}</span></div>'
    )


def _component(index: int, item: dict[str, Any]) -> str:
    name = text(item, "name") or f"Component {index + 1}"
    description = text(item, "description")
    about = f'<span class="component-desc">{escape(description)}</span>' if description else ""
    return (
        f'<figure class="component"><figcaption><strong>{escape(name)}</strong>{about}'
        f'</figcaption><div class="preview" data-component="{index}"></div></figure>'
    )


def _section(heading: str, kind: str, parts: list[str]) -> str:
    if not parts:
        return ""
    return (
        f'<section class="ds-section"><h2>{heading}</h2>'
        f'<div class="{kind}">{"".join(parts)}</div></section>'
    )


def render(title: str, content: str, init: Mapping[str, object] | None) -> str:
    data = parse(content)
    colors = _colors(data)
    background = _background(colors)
    components = items(data, "components")
    sections = "".join(
        (
            _section("Colors", "swatches", [_swatch(color, background) for color in colors]),
            _section(
                "Typography",
                "types",
                [_type(index, item) for index, item in enumerate(items(data, "typography"))],
            ),
            _section(
                "Spacing",
                "spaces",
                [_space(index, item) for index, item in enumerate(items(data, "spacing"))],
            ),
            _section(
                "Radii",
                "radii",
                [_radius(index, item) for index, item in enumerate(items(data, "radii"))],
            ),
            _section(
                "Components",
                "components",
                [_component(index, item) for index, item in enumerate(components)],
            ),
        )
    )
    name = (text(data, "name") if data is not None else "") or title
    description = text(data, "description") if data is not None else ""
    about = f'<p class="desc">{escape(description)}</p>' if description else ""
    empty = '<p class="empty">This design system has nothing to show yet.</p>'
    light = background.light if background else "#ffffff"
    dark = (background.dark if background else None) or "#000000"
    previews = (
        f".preview {{ background: {light}; }}\n"
        f"@media (prefers-color-scheme: dark) {{ .preview {{ background: {dark}; }} }}\n"
    )
    body = (
        '<main class="ds"><header class="ds-head"><p class="eyebrow">Design system</p>'
        f"<h1>{escape(name)}</h1>{about}</header>{sections or empty}</main>\n"
        + json_data("nest-data", [text(item, "html") for item in components])
    )
    return page(
        title=title,
        init=init,
        css=resource("design_system.css") + previews,
        body=body,
        code=script(resource("common.js"), resource("screens.js"), resource("design_system.js")),
    )
