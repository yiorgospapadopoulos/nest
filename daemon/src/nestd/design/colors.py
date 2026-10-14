"""Color strings used in the token file: `#rrggbb` or `rgba(r,g,b,a)`."""

import re
from dataclasses import dataclass

_HEX = re.compile(r"#([0-9a-fA-F]{6})")
_RGBA = re.compile(r"rgba\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d*\.?\d+)\s*\)")


@dataclass(frozen=True)
class RGBA:
    """Channels as fractions from 0 to 1."""

    red: float
    green: float
    blue: float
    alpha: float


def parse_color(text: str) -> RGBA:
    if match := _HEX.fullmatch(text):
        value = int(match[1], 16)
        return RGBA((value >> 16) / 255, (value >> 8 & 0xFF) / 255, (value & 0xFF) / 255, 1.0)
    if match := _RGBA.fullmatch(text):
        red, green, blue = (int(match[index]) for index in (1, 2, 3))
        alpha = float(match[4])
        if max(red, green, blue) <= 255 and alpha <= 1:
            return RGBA(red / 255, green / 255, blue / 255, alpha)
    msg = f"invalid color {text!r}: use #rrggbb or rgba(r,g,b,a)"
    raise ValueError(msg)
