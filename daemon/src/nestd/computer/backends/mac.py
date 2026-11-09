"""Mac apps through the Nest Computer helper, in the background with public APIs only (B150,
D178): accessibility actions and keys sent to the app, never the user's cursor."""

import base64
import sys
from typing import cast

from pydantic import JsonValue

from nestd.computer.helper import Helper, HelperError, JsonObject
from nestd.computer.models import (
    Action,
    ActResult,
    Availability,
    Element,
    NeedsFrontError,
    SecureFieldError,
    TargetError,
    TargetInfo,
    TargetKind,
    View,
    WindowFrame,
)

PREFIX = "mac:"
HIDDEN_NOTE = (
    "Windows on other desktops stay hidden until the user shows them once; or open a new"
    " window through the app's menu (action menu, such as File > New)."
)

NO_SCREENSHOT = "No screenshot; the elements above still work"


def element_of(raw: JsonObject) -> Element:
    actions = raw.get("actions")
    return Element(
        id=str(raw.get("id", "")),
        role=str(raw.get("role", "")),
        label=str(raw.get("label") or ""),
        value=str(raw.get("value") or ""),
        depth=_int(raw.get("depth")),
        enabled=raw.get("enabled") is not False,
        focused=raw.get("focused") is True,
        secure=raw.get("secure") is True,
        field=raw.get("field") is True,
        address=raw.get("address") is True,
        actions=tuple(str(a) for a in actions) if isinstance(actions, list) else (),
    )


def windows_of(raw: JsonObject) -> tuple[tuple[str, str], ...]:
    windows = raw.get("windows")
    if not isinstance(windows, list):
        return ()
    return tuple(
        (str(w.get("id", "")), str(w.get("title") or ""))
        for w in (cast(JsonObject, w) for w in windows if isinstance(w, dict))
    )


def _int(value: JsonValue) -> int:
    return value if isinstance(value, int) else 0


def _objects(value: JsonValue) -> list[JsonObject]:
    return (
        [cast(JsonObject, v) for v in value if isinstance(v, dict)]
        if isinstance(value, list)
        else []
    )


class MacBackend:
    def __init__(self, helper: Helper) -> None:
        self._helper = helper
        # Screenshot pixels per window point, by window id, from the last screenshot.
        self._scales: dict[str, float] = {}

    @property
    def kind(self) -> TargetKind:
        return "mac"

    async def available(self) -> Availability:
        if sys.platform != "darwin":
            return Availability(kind="mac", ready=False, reason="Only on a Mac.")
        if not self._helper.installed:
            return Availability(
                kind="mac", ready=False, reason="Nest Computer is missing from Nest.app."
            )
        return Availability(kind="mac", ready=True)

    async def targets(self) -> list[TargetInfo]:
        return [self._info(app) for app in await self._apps()]

    async def open(self, key: str, url: str | None) -> TargetInfo:
        bundle = _bundle(key)
        await self._call("launch", {"bundle_id": bundle})
        app = await self._app(key)
        return self._info(app)

    async def view(self, key: str, window: str | None, screenshot: bool) -> View:
        app = await self._app(key)
        windows = windows_of(app)
        if window is not None and all(w != window for w, _ in windows):
            # Window ids are the helper's own, for every app: only this app's are read here.
            raise TargetError(f"{window} is not a window of {app.get('name') or key}.")
        chosen = window or (windows[0][0] if windows else None)
        if chosen is None:
            return View(title=str(app.get("name", key)), note=f"No window is open. {HIDDEN_NOTE}")
        tree = await self._call("tree", {"window": chosen})
        image: bytes | None = None
        note = HIDDEN_NOTE if len(windows) <= 1 else None
        if screenshot:
            try:
                image = await self.screenshot(chosen, _frame_width(app, chosen))
            except TargetError as error:
                note = f"{NO_SCREENSHOT}: {error}"
        return View(
            title=str(tree.get("title") or app.get("name") or key),
            window=chosen,
            elements=tuple(element_of(e) for e in _objects(tree.get("elements"))),
            truncated=tree.get("truncated") is True,
            image=image,
            note=note,
            windows=windows,
            frame=_frame(app, chosen),
        )

    async def screenshot(self, window: str, points_width: float) -> bytes:
        shot = await self._call("screenshot", {"window": window})
        width = _int(shot.get("width"))
        if width and points_width:
            self._scales[window] = width / points_width
        return base64.b64decode(str(shot.get("png", "")))

    async def act(self, key: str, action: Action) -> ActResult:
        app = await self._app(key)
        pid = _int(app.get("pid"))
        name = str(app.get("name") or key)
        match action.kind:
            case "press":
                await self._call("press", {"element": _need(action.element)})
                return ActResult(text=f"Pressed {action.element} in {name}.")
            case "set_value":
                await self._call(
                    "set_value", {"element": _need(action.element), "text": action.text or ""}
                )
                return ActResult(text=f"Set {action.element} in {name}.")
            case "focus":
                await self._call("focus", {"element": _need(action.element)})
                return ActResult(text=f"Focused {action.element} in {name}.")
            case "type":
                if action.element:
                    await self._call("focus", {"element": action.element})
                await self._call("type", {"pid": pid, "text": action.text or ""})
                return ActResult(text=f"Typed in {name}.")
            case "key":
                await self._call(
                    "key",
                    {"pid": pid, "key": action.key or "", "modifiers": list(action.modifiers)},
                )
                return ActResult(text=f"Pressed {_keys(action)} in {name}.")
            case "menu":
                result = await self._call("menu", {"pid": pid, "path": list(action.menu)})
                opened = windows_of({"windows": result.get("new_windows")})
                shown = "".join(f' It opened window {w} "{title}".' for w, title in opened)
                return ActResult(
                    text=f"Chose {' > '.join(action.menu)} in {name}.{shown}", new_windows=opened
                )
            case "scroll":
                await self._call(
                    "scroll",
                    {
                        "element": action.element,
                        "pid": pid,
                        "direction": action.direction or "down",
                        "amount": action.amount,
                    },
                )
                return ActResult(text=f"Scrolled {action.direction or 'down'} in {name}.")
            case "click":
                window = action.window or _first_window(app)
                scale = self._scales.get(window, 1.0)
                await self._call(
                    "click",
                    {"window": window, "x": (action.x or 0) / scale, "y": (action.y or 0) / scale},
                )
                return ActResult(text=f"Clicked at {action.x}, {action.y} in {name}.")
            case "navigate":
                raise TargetError("Mac apps have no address; use the browser target for pages.")

    async def front(self, key: str) -> None:
        app = await self._app(key)
        await self._call("front", {"pid": _int(app.get("pid"))})

    async def close(self) -> None:
        await self._helper.close()

    async def _apps(self) -> list[JsonObject]:
        return [
            app
            for app in _objects((await self._call("apps")).get("apps"))
            if isinstance(app.get("bundle_id"), str)
        ]

    async def _app(self, key: str) -> JsonObject:
        bundle = _bundle(key)
        for app in await self._apps():
            if app.get("bundle_id") == bundle:
                return app
        raise TargetError(f"{bundle} is not running; open it first with computer_open.")

    def _info(self, app: JsonObject) -> TargetInfo:
        return TargetInfo(
            key=f"{PREFIX}{app.get('bundle_id')}",
            kind="mac",
            name=str(app.get("name") or app.get("bundle_id")),
            running=True,
            windows=windows_of(app),
        )

    async def _call(self, op: str, args: JsonObject | None = None) -> JsonObject:
        try:
            return await self._helper.call(op, args)
        except HelperError as error:
            if error.code == "secure_field":
                raise SecureFieldError(str(error)) from error
            if error.code == "not_front":
                raise NeedsFrontError(str(error)) from error
            if error.code == "no_permission":
                raise TargetError(
                    "Nest Computer is not allowed to control apps yet. Ask the user to allow"
                    " it in Settings > Computer use."
                ) from error
            if error.code == "stale":
                raise TargetError(f"{error} Look again with computer_view.") from error
            raise TargetError(str(error) or f"{op} failed.") from error


def _bundle(key: str) -> str:
    if not key.startswith(PREFIX) or len(key) == len(PREFIX):
        raise TargetError(f"{key} is not a Mac app target.")
    return key[len(PREFIX) :]


def _need(element: str | None) -> str:
    if not element:
        raise TargetError("This action needs an element id from computer_view.")
    return element


def _first_window(app: JsonObject) -> str:
    windows = windows_of(app)
    if not windows:
        raise TargetError("No window to click in.")
    return windows[0][0]


def _frame(app: JsonObject, window: str) -> WindowFrame | None:
    for raw in _objects(app.get("windows")):
        frame = raw.get("frame")
        if raw.get("id") == window and isinstance(frame, dict):
            values = [frame.get(k) for k in ("x", "y", "width", "height")]
            if all(isinstance(v, int | float) for v in values):
                x, y, width, height = (float(cast(float, v)) for v in values)
                return WindowFrame(x=x, y=y, width=width, height=height)
    return None


def _frame_width(app: JsonObject, window: str) -> float:
    frame = _frame(app, window)
    return frame.width if frame is not None else 0.0


def _keys(action: Action) -> str:
    return "-".join([*(m.capitalize() for m in action.modifiers), (action.key or "").capitalize()])
