import dataclasses
import io
import struct
import zlib
from pathlib import Path

import pytest

from nestd.cli import main
from nestd.design.icon import (
    ICON_COLOR,
    ICON_MASCOT,
    ICON_OUTPUTS,
    TILE,
    generate_icons,
    render_icon,
)
from nestd.design.mascots import load_mascots
from nestd.runtime import Runtime, default_runtime
from tests.design_support import REPO_ROOT, write_mascots

SPRITES = load_mascots(REPO_ROOT / "design" / "mascots.toml").sprites
BODY = (0x8B, 0x7C, 0xF6, 255)
INK = (0x22, 0x1E, 0x29, 255)
DARK_TILE = (0x1E, 0x1E, 0x21, 255)
# At 1024 points the sprite's cells are 50 points, starting at (162, 172).
CELL, LEFT, TOP = 50, 162, 172


class Png:
    """A decoded 8-bit RGBA PNG whose rows use filter 0, as the renderer writes them."""

    def __init__(self, data: bytes) -> None:
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        self.width, self.height = struct.unpack(">II", data[16:24])
        assert data[24:29] == b"\x08\x06\x00\x00\x00", "8-bit RGBA, no interlace"
        idat = b""
        at = 8
        while at < len(data):
            (length,) = struct.unpack(">I", data[at : at + 4])
            kind = data[at + 4 : at + 8]
            body = data[at + 8 : at + 8 + length]
            assert zlib.crc32(kind + body) == struct.unpack(">I", data[at + 8 + length :][:4])[0]
            if kind == b"IDAT":
                idat += body
            at += 12 + length
        raw = zlib.decompress(idat)
        stride = 1 + 4 * self.width
        assert len(raw) == stride * self.height
        self.rows = [raw[y * stride : (y + 1) * stride] for y in range(self.height)]
        assert all(row[0] == 0 for row in self.rows), "every row uses filter 0"

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        row = self.rows[y]
        r, g, b, a = row[1 + 4 * x : 5 + 4 * x]
        return (r, g, b, a)


def cell_center(column: int, row: int) -> tuple[int, int]:
    return (LEFT + column * CELL + CELL // 2, TOP + row * CELL + CELL // 2)


def render(mascot: str = ICON_MASCOT, **options: object) -> Png:
    settings: dict[str, object] = {"size": 1024, "shape": "mac"}
    settings.update(options)
    return Png(render_icon(SPRITES[mascot], ICON_COLOR, **settings))  # type: ignore[arg-type]


def test_the_mac_icon_is_a_dark_tile_with_transparent_corners() -> None:
    png = render()
    assert (png.width, png.height) == (1024, 1024)
    assert png.pixel(0, 0) == (0, 0, 0, 0)
    assert png.pixel(99, 512)[3] == 0
    assert png.pixel(512, 900) == DARK_TILE
    # The corner curve is anti-aliased: a pixel on it is partly covered.
    on_curve = png.pixel(182, 130)[3]
    assert 0 < on_curve < 255


def test_the_sprite_is_drawn_in_the_pixie_tones() -> None:
    png = render()
    rows = SPRITES[ICON_MASCOT]
    assert (rows[7][7], rows[4][4], rows[3][4], rows[4][0], rows[0][0]) == ("#", "e", "o", "+", ".")
    assert png.pixel(*cell_center(7, 7)) == BODY
    assert png.pixel(*cell_center(4, 4)) == INK
    assert png.pixel(*cell_center(4, 3)) == (0xDC, 0xD8, 0xFC, 255)
    assert png.pixel(*cell_center(0, 4)) == (0x61, 0x57, 0xAC, 255)
    assert png.pixel(*cell_center(0, 0))[:3] != BODY[:3]


def test_the_icon_pixie_keeps_its_feet_on_the_dark_tile() -> None:
    rows = SPRITES[ICON_MASCOT]
    assert rows[13] == ".....#..#....."
    assert render().pixel(*cell_center(5, 13)) == BODY


def test_wing_tint_blends_with_the_tile() -> None:
    png = render("bluebell")
    assert SPRITES["bluebell"][5][0] == "*"
    r, g, b, a = png.pixel(*cell_center(0, 5))
    wing = (0xBF, 0xB7, 0xFA)
    assert a == 255
    for channel, tile, tint in zip((r, g, b), DARK_TILE[:3], wing, strict=True):
        assert tile < channel < tint


def test_the_tile_is_black_in_every_appearance() -> None:
    assert TILE.fill == "#1E1E21"


def test_a_sheen_lightens_the_top_of_the_tile_only() -> None:
    png = render()
    top = png.pixel(512, 110)
    assert top[3] == 255
    assert all(channel > tile for channel, tile in zip(top[:3], DARK_TILE[:3], strict=True))
    assert png.pixel(130, 600) == DARK_TILE


def test_a_thin_edge_rings_the_tile() -> None:
    png = render()
    edge = png.pixel(101, 600)
    assert edge[3] == 255
    assert edge[:3] != DARK_TILE[:3]
    assert png.pixel(110, 600) == DARK_TILE


def test_the_full_shape_fills_the_square_at_any_size() -> None:
    png = render(size=192, shape="full")
    assert (png.width, png.height) == (192, 192)
    assert png.pixel(191, 191) == DARK_TILE
    # The sheen lightens the top corner, which is still opaque.
    top = png.pixel(0, 0)
    assert top[3] == 255
    assert top[:3] > DARK_TILE[:3]
    # Cells are 9.375 pixels here; a pixel wholly inside a body cell is the body colour.
    assert png.pixel(100, 102) == BODY
    # A pixel straddling a body cell and the tile is a blend of the two.
    rows = SPRITES[ICON_MASCOT]
    assert (rows[7][3], rows[7][4]) == ("+", "#")
    r, g, b, a = png.pixel(67, 102)
    assert a == 255
    assert (r, g, b) not in {BODY[:3], (0x61, 0x57, 0xAC)}


def test_generate_icons_writes_every_output(tmp_path: Path) -> None:
    write_mascots(tmp_path)
    written = generate_icons(tmp_path)
    assert written == list(ICON_OUTPUTS)
    for relative, output in ICON_OUTPUTS.items():
        png = Png((tmp_path / relative).read_bytes())
        assert (png.width, png.height) == (output.size, output.size)
    assert Png((tmp_path / "apple/support/AppIcon-1024.png").read_bytes()).pixel(0, 0)[3] == 0
    assert (
        Png((tmp_path / "web/build/icons/icon-512.png").read_bytes()).pixel(511, 511) == DARK_TILE
    )


def test_the_repository_icons_match_the_source() -> None:
    for relative in ICON_OUTPUTS:
        expected = render_icon(
            SPRITES[ICON_MASCOT],
            ICON_COLOR,
            size=ICON_OUTPUTS[relative].size,
            shape=ICON_OUTPUTS[relative].shape,
        )
        assert (REPO_ROOT / relative).read_bytes() == expected, f"{relative} is out of date"


def test_the_cli_writes_the_icons(tmp_path: Path) -> None:
    write_mascots(tmp_path)
    out, err = io.StringIO(), io.StringIO()
    runtime: Runtime = dataclasses.replace(default_runtime(), out=out, err=err)
    assert main(["design", "icon", "--root", str(tmp_path)], runtime) == 0
    assert out.getvalue() == "".join(f"Wrote {path}\n" for path in ICON_OUTPUTS)
    assert (tmp_path / "web/build/icons/apple-touch-icon.png").is_file()


def test_the_cli_reports_a_bad_mascot_file(tmp_path: Path) -> None:
    (tmp_path / "design").mkdir()
    (tmp_path / "design" / "mascots.toml").write_text('colors = ["#000000"]\n')
    out, err = io.StringIO(), io.StringIO()
    runtime: Runtime = dataclasses.replace(default_runtime(), out=out, err=err)
    assert main(["design", "icon", "--root", str(tmp_path)], runtime) == 1
    assert "mascots" in err.getvalue()


@pytest.mark.parametrize("size", [16, 180])
def test_small_renders_keep_the_sprite_inside_the_tile(size: int) -> None:
    png = render(size=size, shape="full")
    assert (png.width, png.height) == (size, size)
    assert png.pixel(0, 0)[3] == 255
    assert png.pixel(size - 1, size - 1) == DARK_TILE
