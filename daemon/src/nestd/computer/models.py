"""What every computer-use backend speaks (B150): targets, the outline of a window, and
one action at a time."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TargetKind = Literal["mac", "ios", "android", "browser"]
KINDS: tuple[TargetKind, ...] = ("mac", "ios", "android", "browser")
BROWSER_KEY = "browser"

ActionKind = Literal[
    "press", "set_value", "type", "key", "menu", "scroll", "click", "focus", "navigate"
]
ACTION_KINDS: tuple[ActionKind, ...] = (
    "press",
    "set_value",
    "type",
    "key",
    "menu",
    "scroll",
    "click",
    "focus",
    "navigate",
)
Direction = Literal["up", "down", "left", "right"]
Modifier = Literal["cmd", "shift", "option", "control"]

# The tools' names (B150).
TOOL_NAMES = (
    "computer_targets",
    "computer_open",
    "computer_view",
    "computer_act",
    "computer_release",
)

# The longest side of a screenshot the agent gets, in pixels.
IMAGE_MAX = 1280


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Availability(_Frozen):
    """Whether a kind of target can be used on this computer, and if not, how to get it."""

    kind: TargetKind
    ready: bool
    # Why not, in plain words, such as "Android Studio is not installed."
    reason: str | None = None
    # Where to get what is missing.
    link: str | None = None


class TargetInfo(_Frozen):
    key: str
    kind: TargetKind
    name: str
    # Running, booted or open now.
    running: bool = False
    # Window ids and titles, for Mac apps and the browser's tabs.
    windows: tuple[tuple[str, str], ...] = ()


class Element(_Frozen):
    id: str
    role: str
    label: str = ""
    value: str = ""
    depth: int = 0
    enabled: bool = True
    focused: bool = False
    # A password or other secret field: never typed into (D178).
    secure: bool = False
    # A single-line text field.
    field: bool = False
    # An address or search field, where Return only goes somewhere.
    address: bool = False
    actions: tuple[str, ...] = ()


class View(_Frozen):
    title: str
    window: str | None = None
    elements: tuple[Element, ...] = ()
    truncated: bool = False
    # PNG, the long side at most IMAGE_MAX.
    image: bytes | None = None
    note: str | None = None
    # Every window of the target Nest can see, by id and title, to look at another one.
    windows: tuple[tuple[str, str], ...] = ()


class Action(_Frozen):
    kind: ActionKind
    element: str | None = None
    text: str | None = None
    key: str | None = None
    modifiers: tuple[Modifier, ...] = ()
    menu: tuple[str, ...] = ()
    direction: Direction | None = None
    amount: int = Field(default=3, ge=1, le=50)
    # In screenshot pixels.
    x: int | None = None
    y: int | None = None
    url: str | None = None
    window: str | None = None


class ActResult(_Frozen):
    text: str
    new_windows: tuple[tuple[str, str], ...] = ()


class TargetError(Exception):
    """A backend could not do what was asked; the agent sees the message."""


class NeedsFrontError(TargetError):
    """The action only works with the target in front, which the user must allow first."""


class SecureFieldError(TargetError):
    """The element is a secret field: Nest never types into it (D178)."""


def outline(view: View) -> str:
    """The text the agent reads: one line per element, indented by depth."""
    lines = [f"Window {view.window or '-'}: {view.title}"]
    for element in view.elements:
        lines.append("  " * element.depth + _line(element))
    if view.truncated:
        lines.append("(more elements left out; look at a smaller part or scroll)")
    others = [f'{w} "{title}"' for w, title in view.windows if w != view.window]
    if others:
        lines.append(f"Other windows: {', '.join(others)}")
    if view.note:
        lines.append(view.note)
    return "\n".join(lines)


def _line(element: Element) -> str:
    parts = [element.id, element.role]
    if element.label:
        parts.append(f'"{_short(element.label)}"')
    if element.value:
        parts.append(f"= {_short(element.value)!r}")
    flags = [
        flag
        for flag, on in (
            ("disabled", not element.enabled),
            ("focused", element.focused),
            ("secret", element.secure),
        )
        if on
    ]
    if element.actions:
        flags.extend(element.actions)
    if flags:
        parts.append(f"[{', '.join(flags)}]")
    return " ".join(parts)


def _short(text: str, limit: int = 120) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def kind_of(key: str) -> TargetKind | None:
    if key == BROWSER_KEY:
        return "browser"
    prefix, _, rest = key.partition(":")
    if not rest:
        return None
    for kind in KINDS:
        if prefix == kind and kind != "browser":
            return kind
    return None
