"""Mac apps through the helper (B150): a click given in screenshot pixels lands on the
window's points, as the screenshot is taken at the screen's scale."""

import base64
from pathlib import Path

from nestd.computer.backends.mac import MacBackend
from nestd.computer.helper import Helper, JsonObject
from nestd.computer.models import Action

WINDOW: JsonObject = {
    "id": "w1",
    "title": "Untitled",
    "frame": {"x": 0.0, "y": 0.0, "width": 586.0, "height": 488.0},
}
APP: JsonObject = {
    "pid": 7,
    "bundle_id": "com.apple.TextEdit",
    "name": "TextEdit",
    "windows": [WINDOW],
}


class FakeHelper(Helper):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(tmp_path / "Nest Computer.app", tmp_path / "h.sock")
        self.calls: list[tuple[str, JsonObject]] = []

    async def call(
        self, op: str, args: JsonObject | None = None, time_limit: float = 30.0
    ) -> JsonObject:
        self.calls.append((op, args or {}))
        match op:
            case "apps":
                return {"apps": [APP]}
            case "tree":
                return {"title": "Untitled", "elements": []}
            case "screenshot":
                # A Retina screen: twice the window's points.
                return {"png": base64.b64encode(b"png").decode(), "width": 1172, "height": 976}
            case _:
                return {}


async def test_a_click_in_screenshot_pixels_lands_on_the_windows_points(tmp_path: Path) -> None:
    helper = FakeHelper(tmp_path)
    mac = MacBackend(helper)
    await mac.view("mac:com.apple.TextEdit", None, screenshot=True)

    await mac.act("mac:com.apple.TextEdit", Action(kind="click", x=586, y=488))

    assert helper.calls[-1] == ("click", {"window": "w1", "x": 293.0, "y": 244.0})
