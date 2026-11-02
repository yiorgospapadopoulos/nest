"""The one place a measured value becomes text, so every client shows the same words."""

from typing import Literal

type Unit = Literal["tokens", "ms", "bytes", "percent", "count"]
type Better = Literal["lower", "higher", "none"]
type Direction = Literal["up", "down", "none"]
type Tone = Literal["better", "worse", "same"]

# A change smaller than this share of the previous value shows as no change.
SAME_SHARE = 0.005


def compact(value: float) -> str:
    """1234 as "1.2k", 1_500_000 as "1.5M"; below a thousand at most one decimal."""
    size = abs(value)
    if size >= 999_950:
        return f"{_trim(value / 1_000_000)}M"
    if size >= 1000:
        return f"{_trim(value / 1000)}k"
    return _trim(value)


def _trim(value: float) -> str:
    """One decimal, without a trailing ".0"."""
    text = f"{value:.1f}"
    return text[:-2] if text.endswith(".0") else text


def duration(ms: float) -> str:
    if ms < 1000:
        return f"{round(ms)} ms"
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, rest = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes} min {rest} s" if rest else f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    return f"{hours} h {minutes} min" if minutes else f"{hours} h"


def size(count: float) -> str:
    """Decimal units, as the Finder shows them."""
    for unit, scale in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if abs(count) >= scale:
            return f"{count / scale:.1f} {unit}"
    return f"{round(count)} B"


def percent(value: float) -> str:
    """Whole percents; one decimal below ten, where a point matters."""
    if abs(value) < 10 and round(value, 1) != round(value):
        return f"{value:.1f}%"
    return f"{round(value)}%"


def value_text(value: float | None, unit: Unit) -> str:
    """A dash for a value that could not be measured."""
    if value is None:
        return "-"
    match unit:
        case "tokens" | "count":
            return compact(value)
        case "ms":
            return duration(value)
        case "bytes":
            return size(value)
        case "percent":
            return percent(value)


def delta_text(delta: float, unit: Unit) -> str:
    """The size of a change without its sign: tokens and percents as an amount (a percent
    metric changes by points), everything else relative to the previous value."""
    return value_text(abs(delta), unit)


def relative(value: float, previous: float) -> float | None:
    """The change as a share of the previous value; None when there was nothing before."""
    if previous == 0:
        return None
    return (value - previous) / abs(previous)


def change(
    value: float, previous: float, unit: Unit, better: Better
) -> tuple[str, Direction, Tone]:
    """`▲ 1.2k`, `▼ 25%` or `0%`, with which way it went and whether that is good."""
    share = relative(value, previous)
    if value == previous or (share is not None and abs(share) < SAME_SHARE):
        return "0%", "none", "same"
    direction: Direction = "up" if value > previous else "down"
    arrow = "▲" if direction == "up" else "▼"
    if unit in ("tokens", "percent") or share is None:
        amount = delta_text(value - previous, unit)
    else:
        amount = f"{round(abs(share) * 100)}%"
    if better == "none":
        tone: Tone = "same"
    else:
        tone = "better" if (direction == "down") == (better == "lower") else "worse"
    return f"{arrow} {amount}", direction, tone


def signed(value: float, previous: float, unit: Unit) -> str:
    """`+1.2k` or `-25%`, for the sentences of What changed."""
    sign = "+" if value >= previous else "-"
    share = relative(value, previous)
    if unit in ("tokens", "percent") or share is None:
        return f"{sign}{delta_text(value - previous, unit)}"
    return f"{sign}{round(abs(share) * 100)}%"
