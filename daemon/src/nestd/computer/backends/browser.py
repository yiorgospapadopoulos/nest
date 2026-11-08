"""Nest's shared browser: a Chrome-family browser with its own profile, used through the
Chrome DevTools Protocol (B150). The user's own browser and profile are never touched."""

import asyncio
import base64
import contextlib
import json
import os
import shutil
import sys
from collections.abc import AsyncGenerator, Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, cast

import httpx
from websockets.asyncio.client import ClientConnection, connect

from nestd.computer.images import png_size
from nestd.computer.models import (
    BROWSER_KEY,
    IMAGE_MAX,
    Action,
    ActResult,
    Availability,
    Element,
    SecureFieldError,
    TargetError,
    TargetInfo,
    TargetKind,
    View,
)

CHROME_LINK = "https://www.google.com/chrome/"
MAX_ELEMENTS = 400
START_SECONDS = 20.0
PORT_FILE = "DevToolsActivePort"

MAC_APPS = (
    "Google Chrome.app/Contents/MacOS/Google Chrome",
    "Chromium.app/Contents/MacOS/Chromium",
    "Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "Brave Browser.app/Contents/MacOS/Brave Browser",
)
LINUX_NAMES = (
    "google-chrome",
    "google-chrome-stable",
    "chromium",
    "chromium-browser",
    "microsoft-edge",
    "microsoft-edge-stable",
    "brave-browser",
)

# Containers that only group other nodes, and text runs inside text.
_SKIPPED_ROLES = {"InlineTextBox", "LineBreak"}
_GROUPING_ROLES = {"generic", "none", "GenericContainer", "group", "paragraph", "LayoutTable"}
_TEXT_ROLES = {"textbox", "searchbox", "combobox", "TextField", "textField"}
_PRESS_ROLES = {
    "button",
    "link",
    "checkbox",
    "radio",
    "menuitem",
    "tab",
    "switch",
    "option",
    "PopUpButton",
    "menuitemcheckbox",
    "menuitemradio",
}

# (key, code, Windows key code, text typed)
KEYS: Mapping[str, tuple[str, str, int, str]] = {
    "return": ("Enter", "Enter", 13, "\r"),
    "tab": ("Tab", "Tab", 9, ""),
    "escape": ("Escape", "Escape", 27, ""),
    "delete": ("Backspace", "Backspace", 8, ""),
    "up": ("ArrowUp", "ArrowUp", 38, ""),
    "down": ("ArrowDown", "ArrowDown", 40, ""),
    "left": ("ArrowLeft", "ArrowLeft", 37, ""),
    "right": ("ArrowRight", "ArrowRight", 39, ""),
    "space": (" ", "Space", 32, " "),
    "home": ("Home", "Home", 36, ""),
}
MODIFIER_BITS: Mapping[str, int] = {"option": 1, "control": 2, "cmd": 4, "shift": 8}

_SELECT_ALL = """function () {
  if (typeof this.select === "function") { this.select(); return; }
  const range = document.createRange();
  range.selectNodeContents(this);
  const selection = window.getSelection();
  selection.removeAllRanges();
  selection.addRange(range);
}"""
_FOCUSED_SECURE = """(() => {
  const e = document.activeElement;
  if (!e) return false;
  return e.type === "password" || /^cc-/.test(e.getAttribute("autocomplete") || "");
})()"""

type Json = dict[str, Any]


class Child(Protocol):
    """A process this backend started."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    async def wait(self) -> int: ...


type Spawner = Callable[[Sequence[str]], Awaitable[Child]]


async def _spawn(argv: Sequence[str]) -> Child:
    return await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )


def find_browser(env: Mapping[str, str], home: Path) -> Path | None:
    if sys.platform == "darwin":
        for folder in (Path("/Applications"), home / "Applications"):
            for app in MAC_APPS:
                if (folder / app).is_file():
                    return folder / app
        return None
    for name in LINUX_NAMES:
        found = shutil.which(name, path=env.get("PATH"))
        if found:
            return Path(found)
    return None


@dataclass(frozen=True)
class Ref:
    """An element of a tab's last view, as actions need it."""

    backend_id: int
    secure: bool


@dataclass(frozen=True)
class Mapped:
    title: str
    elements: tuple[Element, ...]
    refs: dict[str, Ref]
    truncated: bool


def map_ax_tree(nodes: Sequence[Json], secure_ids: set[int], address_ids: set[int]) -> Mapped:
    """`Accessibility.getFullAXTree` nodes into elements, in document order. Ignored and
    grouping nodes are left out and their children keep the depth."""
    by_id: dict[str, Json] = {str(node["nodeId"]): node for node in nodes}
    roots = [node for node in nodes if not node.get("parentId")]
    elements: list[Element] = []
    refs: dict[str, Ref] = {}
    title = ""
    truncated = False

    def visit(node: Json, depth: int, parent_label: str) -> None:
        nonlocal title, truncated
        if truncated:
            return
        role = _value(node.get("role"))
        name = _value(node.get("name"))
        backend_id = node.get("backendDOMNodeId")
        keep = not node.get("ignored") and _worth_showing(role, name, parent_label)
        if role == "RootWebArea":
            title = title or name
            keep = False
        child_depth, label = depth, parent_label
        if keep and isinstance(backend_id, int):
            if len(elements) >= MAX_ELEMENTS:
                truncated = True
                return
            element = _element(
                node,
                f"e{len(elements) + 1}",
                depth,
                role,
                name,
                backend_id,
                secure_ids,
                address_ids,
            )
            elements.append(element)
            refs[element.id] = Ref(backend_id, element.secure)
            child_depth, label = depth + 1, name
        for child_id in node.get("childIds", []):
            child = by_id.get(str(child_id))
            if child is not None:
                visit(child, child_depth, label)

    for root in roots:
        visit(root, 0, "")
    return Mapped(title, tuple(elements), refs, truncated)


def _worth_showing(role: str, name: str, parent_label: str) -> bool:
    if role in _SKIPPED_ROLES:
        return False
    if role in _GROUPING_ROLES:
        return bool(name)
    # A button's own text repeats its name.
    return not (role == "StaticText" and (not name or name == parent_label))


def _element(
    node: Json,
    element_id: str,
    depth: int,
    role: str,
    name: str,
    backend_id: int,
    secure_ids: set[int],
    address_ids: set[int],
) -> Element:
    props = {str(p.get("name")): _raw(p.get("value")) for p in node.get("properties", [])}
    text = role in _TEXT_ROLES
    secure = backend_id in secure_ids
    actions: list[str] = []
    if role in _PRESS_ROLES:
        actions.append("press")
    if text:
        actions.append("set_value")
    return Element(
        id=element_id,
        role=role,
        label=name,
        value="" if secure else _value(node.get("value")),
        depth=depth,
        enabled=props.get("disabled") is not True,
        focused=props.get("focused") is True,
        secure=secure,
        field=text and props.get("multiline") is not True,
        address=text and (role == "searchbox" or backend_id in address_ids),
        actions=tuple(actions),
    )


def _raw(holder: object) -> object:
    """The `value` of a CDP AXValue."""
    return cast(Json, holder).get("value") if isinstance(holder, dict) else None


def _value(holder: object) -> str:
    value = _raw(holder)
    return "" if value is None else str(value)


def secure_attributes(attributes: Sequence[str]) -> tuple[bool, bool]:
    """Whether an element with these DOM attributes (name, value, name, value...) is a
    secret field, and whether it is an address or search field."""
    pairs = dict(zip(attributes[::2], attributes[1::2], strict=False))
    kind = pairs.get("type", "").lower()
    secure = kind == "password" or pairs.get("autocomplete", "").lower().startswith("cc-")
    return secure, kind in {"search", "url"}


class Cdp:
    """One DevTools connection to a tab."""

    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket
        self._next = 0

    async def send(self, method: str, params: Json | None = None) -> Json:
        self._next += 1
        ident = self._next
        await self._socket.send(json.dumps({"id": ident, "method": method, "params": params or {}}))
        async with asyncio.timeout(30):
            while True:
                message: Json = json.loads(await self._socket.recv())
                if message.get("id") != ident:
                    continue
                if "error" in message:
                    raise TargetError(f"{method}: {message['error'].get('message', 'failed')}")
                result: Json = message.get("result", {})
                return result


@dataclass(frozen=True)
class Tab:
    id: str
    title: str
    url: str
    socket: str


class BrowserBackend:
    def __init__(
        self,
        profile: Path,
        *,
        executable: Path | None = None,
        spawn: Spawner = _spawn,
        transport: httpx.AsyncBaseTransport | None = None,
        env: Mapping[str, str] | None = None,
        start_seconds: float = START_SECONDS,
    ) -> None:
        self._profile = profile
        self._executable = executable
        self._spawn = spawn
        self._transport = transport
        self._env = os.environ if env is None else env
        self._start_seconds = start_seconds
        self._child: Child | None = None
        self._refs: dict[str, dict[str, Ref]] = {}
        # CSS pixels per screenshot pixel, from each tab's last screenshot.
        self._factors: dict[str, float] = {}

    @property
    def kind(self) -> TargetKind:
        return "browser"

    def _browser(self) -> Path | None:
        return self._executable or find_browser(self._env, Path.home())

    async def available(self) -> Availability:
        if self._browser() is None:
            return Availability(
                kind="browser", ready=False, reason="Chrome is not installed.", link=CHROME_LINK
            )
        return Availability(kind="browser", ready=True)

    def _port(self) -> int | None:
        try:
            first = (self._profile / PORT_FILE).read_text().splitlines()[0]
            return int(first)
        except (OSError, IndexError, ValueError):
            return None

    @contextlib.asynccontextmanager
    async def _http(self) -> AsyncGenerator[tuple[httpx.AsyncClient, str]]:
        port = self._port()
        if port is None:
            raise TargetError("The browser is not running; open it first.")
        async with httpx.AsyncClient(transport=self._transport, timeout=5) as client:
            yield client, f"http://127.0.0.1:{port}"

    async def _running(self) -> bool:
        if self._port() is None:
            return False
        try:
            async with self._http() as (client, base):
                return (await client.get(f"{base}/json/version")).is_success
        except (httpx.HTTPError, TargetError):
            return False

    async def _tabs(self) -> list[Tab]:
        try:
            async with self._http() as (client, base):
                response = await client.get(f"{base}/json/list")
                response.raise_for_status()
                listed: list[Json] = response.json()
        except httpx.HTTPError as error:
            raise TargetError(f"The browser did not answer: {error}") from None
        return [
            Tab(
                str(t["id"]),
                str(t.get("title", "")),
                str(t.get("url", "")),
                str(t.get("webSocketDebuggerUrl", "")),
            )
            for t in listed
            if t.get("type") == "page"
        ]

    async def _info(self, running: bool) -> TargetInfo:
        name = self._browser()
        windows = tuple((t.id, t.title or t.url) for t in await self._tabs()) if running else ()
        label = name.stem if name else "browser"
        return TargetInfo(
            key=BROWSER_KEY,
            kind="browser",
            name=f"Nest browser ({label})",
            running=running,
            windows=windows,
        )

    async def targets(self) -> list[TargetInfo]:
        running = await self._running()
        if not running and self._browser() is None:
            return []
        return [await self._info(running)]

    async def open(self, key: str, url: str | None) -> TargetInfo:
        self._check_key(key)
        if not await self._running():
            await self._start(url)
        elif url:
            async with self._cdp(None) as (cdp, _):
                await self._navigate(cdp, url)
        return await self._info(True)

    def _check_key(self, key: str) -> None:
        if key != BROWSER_KEY:
            raise TargetError(f"Unknown browser target {key}.")

    async def _start(self, url: str | None) -> None:
        browser = self._browser()
        if browser is None:
            raise TargetError("Chrome is not installed.")
        self._profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        (self._profile / PORT_FILE).unlink(missing_ok=True)
        self._child = await self._spawn(
            [
                str(browser),
                f"--user-data-dir={self._profile}",
                "--remote-debugging-port=0",
                "--remote-debugging-address=127.0.0.1",
                "--no-first-run",
                "--no-default-browser-check",
                url or "about:blank",
            ]
        )
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._start_seconds
        while not await self._running():
            if self._child.returncode is not None:
                raise TargetError("The browser stopped while starting.")
            if loop.time() >= deadline:
                raise TargetError(f"The browser did not start within {self._start_seconds:g} s.")
            await asyncio.sleep(0.25)

    @contextlib.asynccontextmanager
    async def _cdp(self, window: str | None) -> AsyncGenerator[tuple[Cdp, Tab]]:
        tabs = await self._tabs()
        tab = next((t for t in tabs if t.id == window), None) if window else None
        if tab is None and window:
            raise TargetError(f"There is no tab {window}.")
        tab = tab or (tabs[0] if tabs else None)
        if tab is None or not tab.socket:
            raise TargetError("The browser has no open page.")
        async with connect(tab.socket, max_size=64 * 1024 * 1024, open_timeout=10) as socket:
            yield Cdp(socket), tab

    async def view(self, key: str, window: str | None, screenshot: bool) -> View:
        self._check_key(key)
        async with self._cdp(window) as (cdp, tab):
            tree = await cdp.send("Accessibility.getFullAXTree")
            nodes: list[Json] = tree.get("nodes", [])
            secure_ids, address_ids = await self._field_kinds(cdp, nodes)
            mapped = map_ax_tree(nodes, secure_ids, address_ids)
            self._refs[tab.id] = mapped.refs
            image = await self._screenshot(cdp, tab.id) if screenshot else None
        return View(
            title=mapped.title or tab.title or tab.url,
            window=tab.id,
            elements=mapped.elements,
            truncated=mapped.truncated,
            image=image,
        )

    async def _field_kinds(self, cdp: Cdp, nodes: Sequence[Json]) -> tuple[set[int], set[int]]:
        secure: set[int] = set()
        address: set[int] = set()
        for node in nodes:
            backend_id = node.get("backendDOMNodeId")
            if node.get("ignored") or not isinstance(backend_id, int):
                continue
            if _value(node.get("role")) not in _TEXT_ROLES:
                continue
            described = await cdp.send("DOM.describeNode", {"backendNodeId": backend_id})
            is_secure, is_address = secure_attributes(described["node"].get("attributes", []))
            if is_secure:
                secure.add(backend_id)
            if is_address:
                address.add(backend_id)
        return secure, address

    async def _viewport(self, cdp: Cdp) -> Json:
        metrics = await cdp.send("Page.getLayoutMetrics")
        viewport: Json = metrics["cssVisualViewport"]
        return viewport

    async def _screenshot(self, cdp: Cdp, tab_id: str) -> bytes:
        viewport = await self._viewport(cdp)
        width, height = float(viewport["clientWidth"]), float(viewport["clientHeight"])
        scale = min(1.0, IMAGE_MAX / max(width, height))
        png = b""
        # A high-density screen doubles the pixels, so the second try shrinks by what is over.
        for _ in range(2):
            clip = {
                "x": viewport["pageX"],
                "y": viewport["pageY"],
                "width": width,
                "height": height,
                "scale": scale,
            }
            shot = await cdp.send("Page.captureScreenshot", {"format": "png", "clip": clip})
            png = base64.b64decode(shot["data"])
            size = png_size(png)
            if size is None:
                raise TargetError("The browser gave no screenshot.")
            if max(size) <= IMAGE_MAX:
                break
            scale *= IMAGE_MAX / max(size)
        size = png_size(png)
        if size is not None:
            self._factors[tab_id] = width / size[0]
        return png

    def _ref(self, tab_id: str, element: str | None) -> Ref:
        if element is None:
            raise TargetError("Name the element to use.")
        ref = self._refs.get(tab_id, {}).get(element)
        if ref is None:
            raise TargetError(f"There is no element {element}; view the page again.")
        return ref

    async def act(self, key: str, action: Action) -> ActResult:
        self._check_key(key)
        before = {t.id for t in await self._tabs()}
        async with self._cdp(action.window) as (cdp, tab):
            text = await self._act(cdp, tab, action)
        if action.kind not in {"press", "click", "key"}:
            return ActResult(text=text)
        new = tuple((t.id, t.title or t.url) for t in await self._tabs() if t.id not in before)
        return ActResult(text=text, new_windows=new)

    async def _act(self, cdp: Cdp, tab: Tab, action: Action) -> str:
        match action.kind:
            case "press":
                ref = self._ref(tab.id, action.element)
                await self._click(cdp, *await self._centre(cdp, ref))
                return f"Pressed {action.element}."
            case "click":
                if action.element is not None:
                    x, y = await self._centre(cdp, self._ref(tab.id, action.element))
                else:
                    x, y = self._page_point(tab.id, action.x, action.y)
                await self._click(cdp, x, y)
                return f"Clicked at {round(x)}, {round(y)}."
            case "focus":
                ref = self._ref(tab.id, action.element)
                await cdp.send("DOM.focus", {"backendNodeId": ref.backend_id})
                return f"Focused {action.element}."
            case "set_value":
                await self._set_value(cdp, self._ref(tab.id, action.element), action.text or "")
                return f"Set {action.element}."
            case "type":
                await self._refuse_focused_secure(cdp)
                await cdp.send("Input.insertText", {"text": action.text or ""})
                return "Typed the text."
            case "key":
                await self._key(cdp, action)
                return f"Pressed {action.key}."
            case "scroll":
                await self._scroll(cdp, tab, action)
                return f"Scrolled {action.direction or 'down'}."
            case "navigate":
                if not action.url:
                    raise TargetError("Give the address to open.")
                await self._navigate(cdp, action.url)
                return f"Opened {action.url}."
            case "menu":
                raise TargetError("The browser has no menu bar here; press the element instead")

    async def _centre(self, cdp: Cdp, ref: Ref) -> tuple[float, float]:
        with contextlib.suppress(TargetError):
            await cdp.send("DOM.scrollIntoViewIfNeeded", {"backendNodeId": ref.backend_id})
        box = await cdp.send("DOM.getBoxModel", {"backendNodeId": ref.backend_id})
        quad: list[float] = box["model"]["content"]
        return sum(quad[0::2]) / 4, sum(quad[1::2]) / 4

    def _page_point(self, tab_id: str, x: int | None, y: int | None) -> tuple[float, float]:
        if x is None or y is None:
            raise TargetError("Give both x and y, or an element.")
        factor = self._factors.get(tab_id)
        if factor is None:
            raise TargetError("Take a screenshot first, so the point can be found.")
        return x * factor, y * factor

    async def _click(self, cdp: Cdp, x: float, y: float) -> None:
        await cdp.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            await cdp.send(
                "Input.dispatchMouseEvent",
                {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1},
            )

    async def _refuse_focused_secure(self, cdp: Cdp) -> None:
        result = await cdp.send(
            "Runtime.evaluate", {"expression": _FOCUSED_SECURE, "returnByValue": True}
        )
        if result.get("result", {}).get("value") is True:
            raise SecureFieldError("The focused field is a secret field; ask the user to type it.")

    async def _set_value(self, cdp: Cdp, ref: Ref, text: str) -> None:
        if ref.secure:
            raise SecureFieldError("That is a secret field; ask the user to type it.")
        await cdp.send("DOM.focus", {"backendNodeId": ref.backend_id})
        resolved = await cdp.send("DOM.resolveNode", {"backendNodeId": ref.backend_id})
        await cdp.send(
            "Runtime.callFunctionOn",
            {"objectId": resolved["object"]["objectId"], "functionDeclaration": _SELECT_ALL},
        )
        if text:
            await cdp.send("Input.insertText", {"text": text})
        else:
            await self._press_key(cdp, KEYS["delete"], 0)

    async def _key(self, cdp: Cdp, action: Action) -> None:
        name = (action.key or "").lower()
        if name in KEYS:
            spec = KEYS[name]
        elif len(name) == 1 and name.isascii() and name.isalnum():
            code = f"Key{name.upper()}" if name.isalpha() else f"Digit{name}"
            spec = (name, code, ord(name.upper()), name)
        else:
            raise TargetError(f"Unknown key {action.key!r}.")
        modifiers = sum(MODIFIER_BITS[m] for m in action.modifiers)
        await self._press_key(cdp, spec, modifiers)

    async def _press_key(self, cdp: Cdp, spec: tuple[str, str, int, str], modifiers: int) -> None:
        key, code, key_code, text = spec
        base = {"key": key, "code": code, "windowsVirtualKeyCode": key_code, "modifiers": modifiers}
        # Text with Cmd or Control held would type the letter instead of the shortcut.
        typed = {"text": text} if text and not modifiers & 6 else {}
        await cdp.send("Input.dispatchKeyEvent", {"type": "keyDown", **base, **typed})
        await cdp.send("Input.dispatchKeyEvent", {"type": "keyUp", **base})

    async def _scroll(self, cdp: Cdp, tab: Tab, action: Action) -> None:
        if action.element is not None:
            x, y = await self._centre(cdp, self._ref(tab.id, action.element))
        else:
            viewport = await self._viewport(cdp)
            x, y = viewport["clientWidth"] / 2, viewport["clientHeight"] / 2
        step = action.amount * 100
        dx, dy = {"down": (0, step), "up": (0, -step), "right": (step, 0), "left": (-step, 0)}[
            action.direction or "down"
        ]
        await cdp.send(
            "Input.dispatchMouseEvent",
            {"type": "mouseWheel", "x": x, "y": y, "deltaX": dx, "deltaY": dy},
        )

    async def _navigate(self, cdp: Cdp, url: str) -> None:
        result = await cdp.send("Page.navigate", {"url": url})
        if result.get("errorText"):
            raise TargetError(f"Could not open {url}: {result['errorText']}")

    async def front(self, key: str) -> None:
        self._check_key(key)
        tabs = await self._tabs()
        if not tabs:
            return
        async with self._http() as (client, base):
            await client.get(f"{base}/json/activate/{tabs[0].id}")

    async def close(self) -> None:
        child, self._child = self._child, None
        if child is None or child.returncode is not None:
            return
        child.terminate()
        try:
            async with asyncio.timeout(10):
                await child.wait()
        except TimeoutError:
            child.kill()
            await child.wait()
