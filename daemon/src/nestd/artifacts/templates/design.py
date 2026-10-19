"""Designs: mockups presented to decide from. The intro first (an About card), then each
mockup with its label badge (the user answers with it), title and short description, then
the screen in a real device frame drawn in CSS: an iPhone-style or iPad-style bezel, a
Safari-style browser, a macOS window, or none. The layout is a stack (default), a grid, tabs,
or the pan and zoom canvas; the viewer can switch, and open any screen fitted large. The page
puts each screen's HTML, by index, into its frame's shadow root, without its scripts.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape

from nestd.artifacts.templates.shared import (
    diagrams,
    items,
    json_data,
    libraries,
    page,
    parse,
    resource,
    script,
    source,
    text,
)

# Name and logical size of each device a screen may be shown on.
DEVICES: dict[str, tuple[str, int, int]] = {
    "phone": ("Phone", 390, 844),
    "tablet": ("Tablet", 834, 1112),
    "desktop": ("Desktop", 1440, 900),
    "square": ("Square", 800, 800),
}
# The frame each device gets by default, and every frame's space around the screen (left,
# top, right, bottom), in the screen's logical pixels.
AUTO_FRAME = {"phone": "phone", "tablet": "tablet", "desktop": "browser", "square": "none"}
FRAMES: dict[str, tuple[int, int, int, int]] = {
    "phone": (14, 14, 14, 14),
    "tablet": (20, 20, 20, 20),
    "browser": (0, 52, 0, 0),
    "window": (0, 38, 0, 0),
    "none": (0, 0, 0, 0),
}
LAYOUTS = ("stack", "grid", "tabs", "canvas")
_LABEL = re.compile(r"[^A-Za-z0-9]")

_ZOOM = (
    '<div class="tools zoom-tools" role="toolbar" aria-label="Zoom">'
    '<button type="button" class="tool" data-zoom="out" aria-label="Zoom out">&minus;</button>'
    '<output id="nest-zoom" class="zoom" aria-live="polite">100%</output>'
    '<button type="button" class="tool" data-zoom="in" aria-label="Zoom in">+</button>'
    '<button type="button" class="tool fit" data-zoom="fit">Fit</button></div>'
)
_LAYOUT_NAMES = {"stack": "Stack", "grid": "Grid", "tabs": "Tabs", "canvas": "Canvas"}
_VIEWER = (
    '<div id="nest-viewer" class="viewer" role="dialog" aria-modal="true"'
    ' aria-labelledby="nest-viewer-title" hidden>'
    '<div class="viewer-bar"><span class="badge viewer-badge"></span>'
    '<h2 id="nest-viewer-title" class="viewer-title"></h2>'
    '<span class="viewer-count"></span>'
    '<button type="button" class="tool" data-step="-1" aria-label="Previous mockup">'
    "&lsaquo;</button>"
    '<button type="button" class="tool" data-step="1" aria-label="Next mockup">&rsaquo;</button>'
    '<button type="button" class="tool viewer-close" aria-label="Close">&times;</button></div>'
    '<div class="viewer-stage"></div></div>'
)
_LOCK = (
    '<svg class="lock" viewBox="0 0 10 12" aria-hidden="true"><path d="M2.5 5V3.5a2.5 2.5 0 0 1'
    ' 5 0V5M1.5 5h7a.5.5 0 0 1 .5.5v5a.5.5 0 0 1-.5.5h-7a.5.5 0 0 1-.5-.5v-5a.5.5 0 0 1 .5-.5z"'
    ' fill="none" stroke="currentColor" stroke-width="1.1"/></svg>'
)
_LIGHTS = '<span class="lights"><i></i><i></i><i></i></span>'


@dataclass(frozen=True)
class _Screen:
    index: int
    label: str
    title: str
    description: str
    device: str
    frame: str
    url: str
    html: str


def _label(item: Mapping[str, object], index: int) -> str:
    for key in ("label", "variant"):
        value = item.get(key)
        if isinstance(value, str) and (label := _LABEL.sub("", value)[:3]):
            return label
    return str(index + 1)


def _chrome(screen: _Screen) -> str:
    """What the frame draws besides the screen."""
    match screen.frame:
        case "phone":
            return '<span class="island"></span>'
        case "tablet":
            return '<span class="camera"></span>'
        case "browser":
            address = escape(screen.url or screen.title)
            return (
                f'<div class="chrome">{_LIGHTS}<span class="address">{_LOCK}'
                f'<span class="address-text">{address}</span></span></div>'
            )
        case "window":
            return (
                f'<div class="chrome">{_LIGHTS}'
                f'<span class="window-title">{escape(screen.title)}</span></div>'
            )
        case _:
            return ""


def _mockup(screen: _Screen) -> str:
    name, width, height = DEVICES[screen.device]
    left, top, right, bottom = FRAMES[screen.frame]
    outer = (width + left + right, height + top + bottom)
    label, title = escape(screen.label), escape(screen.title)
    description = (
        f'<div class="mockup-desc">{source(f"nest-desc-{screen.index}", screen.description)}</div>'
        if screen.description
        else ""
    )
    return (
        f'<article class="mockup" id="mockup-{screen.index}" data-index="{screen.index}"'
        f' data-label="{label}" aria-labelledby="mockup-{screen.index}-title">'
        '<header class="mockup-head">'
        f'<span class="badge" aria-label="Option {label}">{label}</span>'
        f'<h2 class="mockup-title" id="mockup-{screen.index}-title">{title}</h2>'
        f'<span class="mockup-device">{name}</span></header>{description}'
        f'<div class="stage" role="button" tabindex="0" aria-label="Open {label}, {title}, larger">'
        f'<div class="sizer"><div class="device device-{screen.device} frame-{screen.frame}"'
        f' data-width="{outer[0]}" data-height="{outer[1]}"'
        f' style="width: {outer[0]}px; height: {outer[1]}px;'
        f' padding: {top}px {right}px {bottom}px {left}px;">'
        f'{_chrome(screen)}<div class="screen" data-screen="{screen.index}"'
        f' style="width: {width}px; height: {height}px;"></div></div></div></div></article>'
    )


def _screens(data: Mapping[str, object] | None) -> list[_Screen]:
    found: list[_Screen] = []
    for index, item in enumerate(items(dict(data) if data is not None else None, "screens")):
        device = text(item, "device")
        device = device if device in DEVICES else "phone"
        frame = text(item, "frame")
        found.append(
            _Screen(
                index=index,
                label=_label(item, index),
                title=text(item, "title") or f"Screen {index + 1}",
                description=text(item, "description"),
                device=device,
                frame=frame if frame in FRAMES else AUTO_FRAME[device],
                url=text(item, "url"),
                html=text(item, "html"),
            )
        )
    return found


def render(title: str, content: str, init: Mapping[str, object] | None) -> str:
    data = parse(content)
    screens = _screens(data)
    layout = text(data, "layout") if data is not None else ""
    layout = layout if layout in LAYOUTS else "stack"
    intro = (text(data, "intro") or text(data, "notes")) if data is not None else ""
    if data is None:
        mockups = '<p class="empty">This design could not be read.</p>'
    elif not screens:
        mockups = '<p class="empty">This design has no screens.</p>'
    else:
        mockups = "".join(_mockup(screen) for screen in screens)
    count = len(screens)
    switcher = "".join(
        f'<button type="button" class="segment" data-layout="{name}"'
        f' aria-pressed="{"true" if name == layout else "false"}">{label}</button>'
        for name, label in _LAYOUT_NAMES.items()
    )
    tabs = "".join(
        f'<button type="button" role="tab" id="nest-tab-{screen.index}"'
        f' aria-controls="mockup-{screen.index}" aria-selected="false" tabindex="-1">'
        f'<span class="badge">{escape(screen.label)}</span> {escape(screen.title)}</button>'
        for screen in screens
    )
    body = (
        '<header class="design-head"><div class="head-text"><p class="eyebrow">Design</p>'
        f"<h1>{escape(title)}</h1>"
        f'<p class="head-meta">{count} mockup{"" if count == 1 else "s"}</p></div>'
        '<div class="head-tools"><div class="layouts" role="group" aria-label="Layout">'
        f"{switcher}</div>{_ZOOM}</div></header>\n"
        + (
            '<details class="intro nest-pending" open><summary>About</summary>'
            f'<div class="intro-body">{source("nest-notes", intro)}</div></details>\n'
            if intro
            else ""
        )
        + f'<nav class="tabs" role="tablist" aria-label="Mockups">{tabs}</nav>\n'
        + f'<main id="nest-canvas" class="mockups nest-pending" aria-label="Mockups">'
        f'<div id="nest-world" class="world">{mockups}</div></main>\n'
        + _VIEWER
        + "\n"
        + json_data("nest-data", [screen.html for screen in screens])
    )
    return page(
        title=title,
        init=init,
        css=resource("design.css"),
        body=body,
        code=script(
            diagrams(),
            resource("common.js"),
            resource("markdown.js"),
            resource("screens.js"),
            resource("design.js"),
        ),
        libraries=libraries(1),
        attrs=f' data-layout="{layout}"',
        loading=True,
    )
