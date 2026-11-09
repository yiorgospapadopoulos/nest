"""Screenshots small enough for the agent (B150)."""

import asyncio
import struct
import sys
import tempfile
from pathlib import Path

from nestd.computer.models import IMAGE_MAX

_PNG = b"\x89PNG\r\n\x1a\n"


def png_size(png: bytes) -> tuple[int, int] | None:
    """Width and height from the PNG header, or None if it is not a PNG."""
    if len(png) < 24 or not png.startswith(_PNG):
        return None
    width, height = struct.unpack(">II", png[16:24])
    return width, height


async def scale_png(png: bytes, max_side: int = IMAGE_MAX) -> bytes:
    """The PNG with its long side at most `max_side`. Scaled with macOS's `sips`; elsewhere
    the PNG is returned as it is."""
    size = png_size(png)
    if size is None or max(size) <= max_side or sys.platform != "darwin":
        return png
    with tempfile.TemporaryDirectory(prefix="nest-shot-") as folder:
        path = Path(folder) / "shot.png"
        path.write_bytes(png)
        process = await asyncio.create_subprocess_exec(
            "/usr/bin/sips",
            "-Z",
            str(max_side),
            str(path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await process.wait()
        return path.read_bytes() if process.returncode == 0 else png
