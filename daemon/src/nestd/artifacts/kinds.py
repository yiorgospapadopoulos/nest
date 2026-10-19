"""What the content of each ready-made artifact kind must be (B88, D116). Nest builds these
pages itself from templates, so an agent sends data: slides as Markdown split on lines that
are exactly `---`, a design or a design system as JSON. A refusal names the bad field, so
the agent can fix it.
"""

import re
from typing import Annotated, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)
from pydantic_core import ErrorDetails

from nestd.artifacts.models import ArtifactKind, InvalidArtifactError

SLIDES_MAX = 200
SCREENS_MAX = 24
# Bytes of a design screen's and of a design system component's UTF-8 html.
SCREEN_HTML_MAX = 200 * 1024
COMPONENT_HTML_MAX = 50 * 1024
COLORS_MAX = 200
# Of each other list of a design system.
ENTRIES_MAX = 100
NAME_MAX = 80
INTRO_MAX = 4000
DESCRIPTION_MAX = 600
URL_MAX = 200

_SEPARATORS = ("---", "---\r")
_HEX = re.compile(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")
_LABEL = re.compile(r"[A-Za-z0-9]{1,3}")

type Device = Literal["phone", "tablet", "desktop", "square"]
type Frame = Literal["auto", "browser", "window", "phone", "tablet", "none"]
type Layout = Literal["stack", "grid", "tabs", "canvas"]
type _Name = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=NAME_MAX)
]


class _Data(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def _within(html: str, limit: int) -> str:
    size = len(html.encode("utf-8", "surrogatepass"))
    if size > limit:
        msg = f"is {size} bytes; at most {limit}"
        raise ValueError(msg)
    return html


class Screen(_Data):
    """One mockup of a design: a labelled option with its idea, framed like its device."""

    label: Annotated[str, Field(validation_alias=AliasChoices("label", "variant"))]
    title: _Name
    description: Annotated[str, StringConstraints(max_length=DESCRIPTION_MAX)] | None = None
    device: Device
    frame: Frame = "auto"
    # Shown in the browser frame's address bar.
    url: Annotated[str, StringConstraints(max_length=URL_MAX)] | None = None
    html: str

    @field_validator("label")
    @classmethod
    def _label(cls, label: str) -> str:
        if not _LABEL.fullmatch(label):
            msg = "must be 1 to 3 letters or digits, such as A, B2 or 10"
            raise ValueError(msg)
        return label

    @field_validator("html")
    @classmethod
    def _html(cls, html: str) -> str:
        return _within(html, SCREEN_HTML_MAX)


class Design(_Data):
    """Mockups presented for a decision (D116): an intro, then each screen in turn."""

    intro: Annotated[
        str | None,
        StringConstraints(max_length=INTRO_MAX),
        Field(validation_alias=AliasChoices("intro", "notes")),
    ] = None
    layout: Layout = "stack"
    screens: Annotated[list[Screen], Field(min_length=1, max_length=SCREENS_MAX)]


def _hex(color: str | None) -> str | None:
    if color is not None and not _HEX.fullmatch(color):
        msg = "must be a hex colour such as #4C6EF5 (#rgb, #rrggbb or #rrggbbaa)"
        raise ValueError(msg)
    return color


class Color(_Data):
    name: _Name
    light: str
    dark: str | None = None
    role: str | None = None

    _colors = field_validator("light", "dark")(_hex)


class TextStyle(_Data):
    name: _Name
    family: str
    size: Annotated[float, Field(gt=0)]
    weight: Annotated[int, Field(ge=1, le=1000)]
    line_height: Annotated[float, Field(gt=0)]
    sample: str | None = None


class Measure(_Data):
    name: _Name
    value: Annotated[float, Field(ge=0)]


class Component(_Data):
    name: _Name
    html: str
    description: str | None = None

    @field_validator("html")
    @classmethod
    def _html(cls, html: str) -> str:
        return _within(html, COMPONENT_HTML_MAX)


class DesignSystem(_Data):
    name: _Name
    description: str | None = None
    colors: Annotated[list[Color], Field(min_length=1, max_length=COLORS_MAX)]
    typography: Annotated[list[TextStyle], Field(max_length=ENTRIES_MAX)] = []
    spacing: Annotated[list[Measure], Field(max_length=ENTRIES_MAX)] = []
    radii: Annotated[list[Measure], Field(max_length=ENTRIES_MAX)] = []
    components: Annotated[list[Component], Field(max_length=ENTRIES_MAX)] = []


# What to send instead, when the content is not JSON (agents tend to send a page).
_SHAPES: dict[str, str] = {
    "design": (
        '{"intro": "What is being decided", "layout": "stack", "screens": [{"label": "A",'
        ' "title": "Settings", "description": "The idea and its trade-off", "device": "phone",'
        ' "frame": "auto", "html": "<style>...</style><main>...</main>"}]}; put each option\'s'
        " HTML in a screen's html"
    ),
    "design system": (
        '{"name": "...", "colors": [{"name": "accent", "light": "#4C6EF5", "dark": "#7B93FF"}],'
        ' "typography": [{"name": "Title", "family": "-apple-system, sans-serif", "size": 28,'
        ' "weight": 700, "line_height": 1.2}], "spacing": [{"name": "s", "value": 8}],'
        ' "radii": [{"name": "card", "value": 16}], "components": [{"name": "Primary button",'
        ' "html": "<style>...</style><button>...</button>"}]}; put each component\'s HTML in'
        " a component's html"
    ),
}
_MODELS: dict[ArtifactKind, tuple[type[_Data], str]] = {
    "design": (Design, "design"),
    "design_system": (DesignSystem, "design system"),
}


def slides_of(content: str) -> list[str]:
    """The Markdown of each slide, in order."""
    slides: list[list[str]] = [[]]
    for line in content.split("\n"):
        if line in _SEPARATORS:
            slides.append([])
        else:
            slides[-1].append(line)
    return ["\n".join(lines) for lines in slides]


def checked_kind_content(kind: ArtifactKind, content: str) -> None:
    """Refuses content its kind's template cannot show; Markdown, HTML and documents take any."""
    if kind == "slides":
        _check_slides(content)
    elif kind in _MODELS:
        model, label = _MODELS[kind]
        try:
            model.model_validate_json(content)
        except ValidationError as error:
            raise InvalidArtifactError(_problems(error, label)) from error


def _check_slides(content: str) -> None:
    slides = slides_of(content)
    if len(slides) > SLIDES_MAX:
        msg = f"the deck has {len(slides)} slides; it may have at most {SLIDES_MAX}"
        raise InvalidArtifactError(msg)
    for number, slide in enumerate(slides, start=1):
        if not slide.strip():
            msg = (
                f"slide {number} is empty; slides are separated by a line that is exactly ---,"
                " and each needs content"
            )
            raise InvalidArtifactError(msg)


def _problems(error: ValidationError, label: str) -> str:
    details = error.errors(include_url=False)
    if details[0]["type"] == "json_invalid":
        reason = details[0].get("ctx", {}).get("error", "")
        return (
            f"the content of a {label} must be JSON, not HTML: {_SHAPES[label]}"
            f" (the JSON parser said: {reason})"
        )
    return f"the {label} is not valid: " + "; ".join(_problem(d, label) for d in details)


def _problem(detail: ErrorDetails, label: str) -> str:
    if not detail["loc"]:
        return f"the content of a {label} must be a JSON object"
    path = "".join(f"[{part}]" if isinstance(part, int) else f".{part}" for part in detail["loc"])
    return f"{path.removeprefix('.')} {_message(detail)}"


def _message(detail: ErrorDetails) -> str:
    ctx = detail.get("ctx", {})
    match detail["type"]:
        case "missing":
            return "is required"
        case "extra_forbidden":
            return "is not a known field"
        case "literal_error":
            return f"must be {str(ctx['expected']).replace("'", '')}"
        case "string_type":
            return "must be a string"
        case "list_type":
            return "must be a list"
        case "model_type":
            return "must be an object"
        case "int_type":
            return "must be an integer"
        case "float_type":
            return "must be a number"
        case "greater_than":
            return f"must be greater than {ctx['gt']}"
        case "greater_than_equal":
            return f"must be at least {ctx['ge']}"
        case "less_than_equal":
            return f"must be at most {ctx['le']}"
        case "string_too_short":
            return "needs text"
        case "string_too_long":
            return f"has at most {ctx['max_length']} characters"
        case "too_short":
            count = ctx["min_length"]
            return f"needs at least {count} item{'' if count == 1 else 's'}"
        case "too_long":
            return f"has at most {ctx['max_length']} items"
        case "value_error":
            return str(ctx["error"])
        case _:
            return detail["msg"]
