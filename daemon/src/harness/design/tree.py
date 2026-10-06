"""Turn the token models into a tree of named groups and typed leaves for the emitters.

Accents and wallpapers are not part of the tree: each emitter renders them in its own shape.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from harness.design.models import Glass, Motion, StatusColors, ThemedColor, Tokens, Typography


class Unit(Enum):
    POINTS = "px"
    MILLISECONDS = "ms"
    PERCENT = "%"
    PLAIN = ""


@dataclass(frozen=True)
class Measure:
    value: float
    unit: Unit


@dataclass(frozen=True)
class FontStack:
    families: tuple[str, ...]


@dataclass(frozen=True)
class Bezier:
    x1: float
    y1: float
    x2: float
    y2: float


type Value = ThemedColor | Measure | FontStack | Bezier


@dataclass(frozen=True)
class Leaf:
    name: str
    value: Value


@dataclass(frozen=True)
class Group:
    name: str
    children: tuple["Node", ...]


type Node = Leaf | Group


def format_number(value: float) -> str:
    """Up to six decimals without trailing zeros, so output is stable and readable."""
    return f"{value:.6f}".rstrip("0").rstrip(".")


def token_tree(tokens: Tokens) -> tuple[Group, ...]:
    """Sections in output order, without accents and wallpapers."""
    return (
        Group("colors", tuple(_colors(name, group) for name, group in tokens.colors.items())),
        Group("status", tuple(_status(name, colors) for name, colors in tokens.status.items())),
        _glass(tokens.glass),
        _measures("radius", tokens.radius, Unit.POINTS),
        _measures("spacing", tokens.spacing, Unit.POINTS),
        _typography(tokens.typography),
        _motion(tokens.motion),
    )


def _colors(name: str, colors: Mapping[str, ThemedColor]) -> Group:
    return Group(name, tuple(Leaf(key, color) for key, color in colors.items()))


def _status(name: str, colors: StatusColors) -> Group:
    return _colors(name, {"fill": colors.fill, "text": colors.text, "soft": colors.soft})


def _measures(name: str, values: Mapping[str, float], unit: Unit) -> Group:
    return Group(name, tuple(Leaf(key, Measure(value, unit)) for key, value in values.items()))


def _glass(glass: Glass) -> Group:
    tint = glass.tint
    return Group(
        "glass",
        (
            _colors("tint", {"regular": tint.regular, "strong": tint.strong, "clear": tint.clear}),
            Leaf("border", glass.border),
            Leaf("specular", glass.specular),
            Leaf("outline", glass.outline),
            Leaf("shadow", glass.shadow),
            _measures(
                "blur", {"normal": glass.blur.normal, "heavy": glass.blur.heavy}, Unit.POINTS
            ),
            Leaf("saturation", Measure(glass.saturation, Unit.PERCENT)),
        ),
    )


def _typography(typography: Typography) -> Group:
    families = tuple(
        Leaf(name, FontStack(tuple(stack))) for name, stack in typography.family.items()
    )
    return Group(
        "typography",
        (
            Group("family", families),
            _measures("size", typography.size, Unit.POINTS),
            _measures("weight", typography.weight, Unit.PLAIN),
            _measures("line_height", typography.line_height, Unit.PLAIN),
        ),
    )


def _motion(motion: Motion) -> Group:
    easings = tuple(Leaf(name, Bezier(*points)) for name, points in motion.easing.items())
    return Group(
        "motion",
        (
            _measures("duration", motion.duration, Unit.MILLISECONDS),
            Group("easing", easings),
        ),
    )
