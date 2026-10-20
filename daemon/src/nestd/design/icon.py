"""The app icon: the icon pixie's sprite on a tile, written as PNG without image libraries (B95).

`nestd design icon` renders the Mac icon source (the tile on transparent, on the macOS icon
grid), the sprite alone for the Tahoe `.icon` bundle (the system draws the tile from its
`icon.json`), and the PWA icons (the tile filling the square). Cells are blended exactly where
they fall between pixels, so every size comes out of the same sprite.
"""

import math
import struct
import zlib
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Literal

from nestd.design.mascots import INK, MASCOTS_FILE, TONES, load_mascots

ICON_MASCOT = "nightshade"
ICON_COLOR = "#8B7CF6"

# "mac": the tile inset on the macOS icon grid, transparent around it. "full": the tile fills
# the square (PWA icons, masked by the device). "sprite": the sprite alone on transparency.
Shape = Literal["mac", "full", "sprite"]

Rgb = tuple[float, float, float]
# Premultiplied red, green, blue and alpha, each 0 to 1.
Premul = tuple[float, float, float, float]


@dataclass(frozen=True)
class Tile:
    """The tile behind the sprite: its fill, a white sheen fading from the top at `sheen`
    strength, and a thin edge in `edge` at `edge_alpha`."""

    fill: str
    sheen: float
    edge: str
    edge_alpha: float


# The black tile, the same in light and dark mode (D120).
TILE = Tile("#1E1E21", 0.08, "#FFFFFF", 0.12)


@dataclass(frozen=True)
class IconOutput:
    size: int
    shape: Shape


ICON_OUTPUTS: dict[Path, IconOutput] = {
    Path("apple/support/AppIcon-1024.png"): IconOutput(1024, "mac"),
    Path("apple/support/AppIcon.icon/Assets/pixie.png"): IconOutput(1024, "sprite"),
    Path("web/build/icons/icon-512.png"): IconOutput(512, "full"),
    Path("web/build/icons/icon-192.png"): IconOutput(192, "full"),
    Path("web/build/icons/apple-touch-icon.png"): IconOutput(180, "full"),
}

# The geometry at 1024 points: the macOS tile is 824 wide with a 22.37 percent corner; the
# sprite's 14 cells are 50 points each, centred and 10 points down; the edge is 4 wide; the
# sheen fades out over the top 55 percent of the tile.
CANVAS = 1024
TILE_INSET = 100
TILE_SIDE = 824
CORNER = 0.2237 * TILE_SIDE
CELL = 50
CELLS = 14
SPRITE_DROP = 10
EDGE = 4
SHEEN_END = 0.55
_SUBROWS = 4
_WHITE: Rgb = (1.0, 1.0, 1.0)
_CLEAR: Premul = (0.0, 0.0, 0.0, 0.0)
_TONE_OF = {"+": TONES["shade"], "o": TONES["light"], "*": TONES["wing"]}


def _rgb(color: str) -> Rgb:
    r, g, b = (int(color[at : at + 2], 16) for at in (1, 3, 5))
    return (r / 255, g / 255, b / 255)


def _mix(color: Rgb, toward: Rgb, amount: float) -> Rgb:
    """`color` moved `amount` of the way to `toward`, rounded per channel as the clients do."""
    return tuple(
        math.floor((c + (t - c) * amount) * 255 + 0.5) / 255
        for c, t in zip(color, toward, strict=True)
    )  # type: ignore[return-value]


def _cell_fills(color: str) -> dict[str, tuple[Rgb, float]]:
    """Each cell code's straight colour and opacity; "." is absent."""
    body = _rgb(color)
    fills: dict[str, tuple[Rgb, float]] = {
        "#": (body, 1.0),
        "e": (_rgb(INK), 1.0),
        "k": (_rgb(INK), 1.0),
    }
    for code, tone in _TONE_OF.items():
        fills[code] = (_mix(body, _rgb(tone.toward), tone.amount), tone.opacity)
    return fills


def _over(background: Premul, fill: Rgb, opacity: float) -> Premul:
    keep = 1 - opacity
    return (
        background[0] * keep + fill[0] * opacity,
        background[1] * keep + fill[1] * opacity,
        background[2] * keep + fill[2] * opacity,
        background[3] * keep + opacity,
    )


def _weights(start: float, cell: float, count: int, size: int) -> list[list[tuple[int, float]]]:
    """For each pixel along one axis, the cells it overlaps with the share of the pixel each
    covers; cells outside the grid are index -1 (nothing)."""
    result: list[list[tuple[int, float]]] = []
    for pixel in range(size):
        parts: list[tuple[int, float]] = []
        first = math.floor((pixel - start) / cell)
        last = math.floor((pixel + 1 - start) / cell + 1e-9)
        for index in range(first, last + 1):
            low = max(pixel, start + index * cell)
            high = min(pixel + 1, start + (index + 1) * cell)
            if high - low > 1e-9:
                parts.append((index if 0 <= index < count else -1, high - low))
        result.append(parts)
    return result


class _Renderer:
    def __init__(
        self, sprite: tuple[str, ...], color: str, size: int, shape: Shape, tile: Tile
    ) -> None:
        self.sprite = sprite
        self.size = size
        self.shape = shape
        self.tile = tile
        self.fills = _cell_fills(color)
        scale = size / CANVAS
        self.center = size / 2
        self.half = TILE_SIDE / 2 * scale if shape == "mac" else size / 2
        self.corner = CORNER * scale
        self.edge = EDGE * scale
        cell = CELL * scale
        origin = (size - CELLS * cell) / 2
        self.columns = _weights(origin, cell, CELLS, size)
        self.rows = _weights(origin + SPRITE_DROP * scale, cell, CELLS, size)
        self.tile_fill = _rgb(tile.fill)
        self.edge_fill = _rgb(tile.edge)
        self.tile_top = self.center - self.half

    def half_width(self, dy: float, inset: float = 0.0) -> float:
        """The tile's half width at `dy` from its centre, for the tile inset by `inset`."""
        half = self.half - inset
        radius = self.corner - inset
        straight = half - radius
        dy = abs(dy)
        if dy <= straight:
            return half
        if dy >= half:
            return 0.0
        return straight + math.sqrt(radius * radius - (dy - straight) ** 2)

    def coverage(self, x: int, widths: list[float]) -> float:
        """How much of pixel column `x` the tile covers, averaged over the row's samples."""
        total = 0.0
        for width in widths:
            left, right = self.center - width, self.center + width
            total += max(0.0, min(x + 1, right) - max(x, left))
        return total / len(widths)

    def row_widths(self, y: int, inset: float = 0.0) -> list[float]:
        if self.shape == "full":
            return [self.half]
        samples = range(_SUBROWS)
        return [self.half_width(y + (s + 0.5) / _SUBROWS - self.center, inset) for s in samples]

    def tile_row(self, y: int) -> Rgb:
        """The tile's colour on pixel row `y`: its fill under the sheen."""
        along = (y + 0.5 - self.tile_top) / (2 * self.half)
        strength = self.tile.sheen * max(0.0, 1 - along / SHEEN_END)
        return _over((*self.tile_fill, 1.0), _WHITE, strength)[:3]

    def pixel(self, x: int, y: int, outer: list[float], inner: list[float], tile: Rgb) -> bytes:
        background = _CLEAR
        edge = 0.0
        if self.shape != "sprite":
            cover = self.coverage(x, outer)
            background = (tile[0] * cover, tile[1] * cover, tile[2] * cover, cover)
            if self.shape == "mac":
                edge = (cover - self.coverage(x, inner)) * self.tile.edge_alpha
        result = [0.0, 0.0, 0.0, 0.0]
        for row, row_weight in self.rows[y]:
            for column, column_weight in self.columns[x]:
                code = self.sprite[row][column] if row >= 0 and column >= 0 else "."
                fill = self.fills.get(code)
                colour = background if fill is None else _over(background, *fill)
                weight = row_weight * column_weight
                for channel in range(4):
                    result[channel] += colour[channel] * weight
        if edge > 0:
            result = list(_over((result[0], result[1], result[2], result[3]), self.edge_fill, edge))
        alpha = result[3]
        straight = [channel / alpha if alpha > 0 else 0.0 for channel in result[:3]]
        return bytes(round(min(1.0, max(0.0, value)) * 255) for value in (*straight, alpha))

    def row(self, y: int) -> bytes:
        outer = self.row_widths(y)
        inner = self.row_widths(y, self.edge) if self.shape == "mac" else outer
        tile = self.tile_row(y)
        # Pixels whose colour may differ from their neighbour's: the tile's edge zones and
        # every sprite cell boundary. Between two stops every pixel is the same.
        stops: set[int] = {0, self.size}
        if self.shape == "mac":
            far, near = max(outer), min(inner)
            for low, high in (
                (self.center - far, self.center - near),
                (self.center + near, self.center + far),
            ):
                stops.update(
                    range(max(0, math.floor(low) - 1), min(self.size, math.ceil(high) + 2))
                )
        if any(index >= 0 for index, _ in self.rows[y]):
            previous: list[tuple[int, float]] = []
            for x, parts in enumerate(self.columns):
                if parts != previous or len(parts) > 1:
                    stops.add(x)
                    stops.add(x + 1)
                previous = parts
        ordered = sorted(stops)
        out = bytearray()
        for start, end in pairwise(ordered):
            out += self.pixel(start, y, outer, inner, tile) * (end - start)
        return bytes(out)


def _png(size: int, rows: list[bytes]) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    data = zlib.compress(b"".join(b"\x00" + row for row in rows), 9)
    return (
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", data) + chunk(b"IEND", b"")
    )


def render_icon(sprite: tuple[str, ...], color: str, *, size: int, shape: Shape) -> bytes:
    """The icon as a `size` by `size` PNG."""
    renderer = _Renderer(sprite, color, size, shape, TILE)
    return _png(size, [renderer.row(y) for y in range(size)])


def generate_icons(root: Path) -> list[Path]:
    """Write every icon file under `root` from the icon pixie's sprite; raises ValueError for
    a bad mascot file."""
    sprite = load_mascots(root / MASCOTS_FILE).sprites[ICON_MASCOT]
    for relative, output in ICON_OUTPUTS.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(render_icon(sprite, ICON_COLOR, size=output.size, shape=output.shape))
    return list(ICON_OUTPUTS)
