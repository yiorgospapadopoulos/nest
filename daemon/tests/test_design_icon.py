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
    generate_icons,
    render_icon,
)
from nestd.design.mascots import load_mascots
from nestd.runtime import Runtime, default_runtime
from tests.design_support import REPO_ROOT, write_mascots

SPRITES = load_mascots(REPO_ROOT / "design" / "mascots.toml").sprites
DARK_TILE = (0x1E, 0x1E, 0x21, 255)


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


def render(mascot: str = ICON_MASCOT, **options: object) -> Png:
    settings: dict[str, object] = {"size": 1024, "shape": "mac"}
    settings.update(options)
    return Png(render_icon(SPRITES[mascot], ICON_COLOR, **settings))  # type: ignore[arg-type]


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
