"""Android devices and emulators through `adb` and `emulator` from Android Studio's SDK
(B150)."""

import asyncio
import contextlib
import os
import shlex
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from nestd.computer.images import png_size, scale_png
from nestd.computer.models import (
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
from nestd.gitops.runner import CommandError, CommandRunner, run_command

STUDIO_LINK = "https://developer.android.com/studio"
MAX_ELEMENTS = 400
# A uiautomator dump of a busy screen is well under a megabyte.
MAX_DUMP_BYTES = 8 * 1024 * 1024
BOOT_SECONDS = 240.0
_POLL_SECONDS = 2.0
_FIRST_PORT = 5554
_LAST_PORT = 5682

# Runs argv and returns its raw stdout, for screenshots.
type BinaryRunner = Callable[[Sequence[str]], Awaitable[bytes]]
# Shrinks a PNG so its long side is at most the given size.
type PngScaler = Callable[[bytes, int], Awaitable[bytes]]

KEYCODES: Mapping[str, str] = {
    "return": "KEYCODE_ENTER",
    "tab": "KEYCODE_TAB",
    "escape": "KEYCODE_ESCAPE",
    "delete": "KEYCODE_DEL",
    "up": "KEYCODE_DPAD_UP",
    "down": "KEYCODE_DPAD_DOWN",
    "left": "KEYCODE_DPAD_LEFT",
    "right": "KEYCODE_DPAD_RIGHT",
    "space": "KEYCODE_SPACE",
    "home": "KEYCODE_HOME",
    "back": "KEYCODE_BACK",
}

_ADDRESS_WORDS = ("url", "address", "search", "omnibox")


class Child(Protocol):
    """A process this backend started."""

    @property
    def pid(self) -> int: ...

    @property
    def returncode(self) -> int | None: ...

    def terminate(self) -> None: ...

    async def wait(self) -> int: ...


type Spawner = Callable[[Sequence[str]], Awaitable[Child]]


@dataclass(frozen=True)
class Node:
    """An element of the last view, as actions need it."""

    x: int
    y: int
    height: int
    secure: bool
    focused: bool
    value: str


@dataclass(frozen=True)
class Screen:
    elements: tuple[Element, ...]
    nodes: dict[str, Node]
    truncated: bool
    width: int
    height: int
    title: str


def find_tool(name: str, subdir: str, env: Mapping[str, str], home: Path) -> Path | None:
    """`name` on PATH, or in the SDK's `subdir` under the usual SDK folders."""
    found = shutil.which(name, path=env.get("PATH"))
    if found:
        return Path(found)
    roots = [env.get("ANDROID_HOME"), env.get("ANDROID_SDK_ROOT")]
    candidates = [Path(root) for root in roots if root]
    candidates += [home / "Library/Android/sdk", home / "Android/Sdk"]
    for root in candidates:
        tool = root / subdir / name
        if tool.is_file() and os.access(tool, os.X_OK):
            return tool
    return None


def parse_dump(text: str) -> Screen:
    """A `uiautomator dump` into elements: nodes with nothing to read or do are left out,
    their children keep the depth."""
    start, end = text.find("<hierarchy"), text.rfind("</hierarchy>")
    if start == -1 or end == -1:
        raise TargetError("The screen could not be read; try again once the device is unlocked.")
    xml = text[start : end + len("</hierarchy>")]
    if len(xml.encode()) > MAX_DUMP_BYTES:
        raise TargetError("The screen is too large to read.")
    root = ET.fromstring(xml)  # noqa: S314 (local, size-limited)
    elements: list[Element] = []
    nodes: dict[str, Node] = {}
    truncated = False
    width = height = 0
    title = ""

    def visit(node: ET.Element, depth: int) -> None:
        nonlocal truncated, width, height, title
        bounds = _bounds(node.get("bounds", ""))
        if bounds is not None and width == 0:
            width, height = bounds[2], bounds[3]
        if not title and node.get("package"):
            title = node.get("package", "")
        element = _element(node, f"e{len(elements) + 1}", depth)
        child_depth = depth
        if element is not None and bounds is not None:
            if len(elements) >= MAX_ELEMENTS:
                truncated = True
                return
            elements.append(element)
            left, top, right, bottom = bounds
            nodes[element.id] = Node(
                x=(left + right) // 2,
                y=(top + bottom) // 2,
                height=bottom - top,
                secure=element.secure,
                focused=element.focused,
                value=element.value,
            )
            child_depth = depth + 1
        for child in node.findall("node"):
            visit(child, child_depth)

    for top_node in root.findall("node"):
        visit(top_node, 0)
    return Screen(tuple(elements), nodes, truncated, width, height, title)


def _element(node: ET.Element, element_id: str, depth: int) -> Element | None:
    cls = node.get("class", "")
    role = cls.rsplit(".", 1)[-1] or "View"
    text = node.get("text", "")
    desc = node.get("content-desc", "")
    hint = node.get("hint", "")
    resource = node.get("resource-id", "")
    clickable = node.get("clickable") == "true"
    scrollable = node.get("scrollable") == "true"
    editable = cls.endswith(("EditText", "AutoCompleteTextView"))
    if not (text or desc or clickable or scrollable or editable):
        return None
    secure = node.get("password") == "true"
    actions: list[str] = []
    if clickable:
        actions.append("press")
    if editable:
        actions.append("set_value")
    if scrollable:
        actions.append("scroll")
    named = f"{resource} {hint}".lower()
    return Element(
        id=element_id,
        role=role,
        label=desc or hint if editable else desc or text,
        value="" if secure or not editable else text,
        depth=depth,
        enabled=node.get("enabled", "true") == "true",
        focused=node.get("focused") == "true",
        secure=secure,
        field=editable,
        address=editable and any(word in named for word in _ADDRESS_WORDS),
        actions=tuple(actions),
    )


def _bounds(text: str) -> tuple[int, int, int, int] | None:
    # "[0,84][1080,210]"
    try:
        first, second = text.strip("[]").split("][")
        left, top = (int(n) for n in first.split(","))
        right, bottom = (int(n) for n in second.split(","))
    except ValueError:
        return None
    return left, top, right, bottom


def text_commands(text: str) -> list[list[str]]:
    """The `input` commands that type `text`: words for `input text`, quoted for the
    device's shell, with Return as a key press."""
    if not text.isascii():
        raise TargetError("Android's input only types plain ASCII text.")
    commands: list[list[str]] = []
    for index, line in enumerate(text.split("\n")):
        if index:
            commands.append(["input", "keyevent", "KEYCODE_ENTER"])
        # `input text` reads "%s" as a space, so a literal "%s" is typed in two goes.
        for piece in _split_percent_s(line):
            commands.append(["input", "text", shlex.quote(piece.replace(" ", "%s"))])
    return commands


def _split_percent_s(line: str) -> list[str]:
    pieces = line.split("%s")
    out: list[str] = []
    for index, piece in enumerate(pieces):
        start = piece if index == 0 else "s" + piece
        if index < len(pieces) - 1:
            start += "%"
        if start:
            out.append(start)
    return out


async def _run_binary(argv: Sequence[str]) -> bytes:
    process = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    try:
        async with asyncio.timeout(30):
            stdout, stderr = await process.communicate()
    except TimeoutError:
        process.kill()
        await process.wait()
        raise CommandError(argv, None, "timed out after 30 seconds") from None
    if process.returncode:
        raise CommandError(argv, process.returncode, stderr.decode(errors="replace"))
    return stdout


async def _spawn(argv: Sequence[str]) -> Child:
    return await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )


@dataclass
class _Started:
    child: Child
    serial: str


class AndroidBackend:
    def __init__(
        self,
        *,
        runner: CommandRunner = run_command,
        binary: BinaryRunner = _run_binary,
        spawn: Spawner = _spawn,
        scale: PngScaler = scale_png,
        env: Mapping[str, str] | None = None,
        home: Path | None = None,
        boot_seconds: float = BOOT_SECONDS,
    ) -> None:
        self._runner = runner
        self._binary = binary
        self._spawn = spawn
        self._scale = scale
        self._env = os.environ if env is None else env
        self._home = Path.home() if home is None else home
        self._boot_seconds = boot_seconds
        self._screens: dict[str, Screen] = {}
        # Device pixels per screenshot pixel, from each serial's last screenshot.
        self._factors: dict[str, float] = {}
        self._started: dict[str, _Started] = {}

    @property
    def kind(self) -> TargetKind:
        return "android"

    def _adb(self) -> Path:
        adb = find_tool("adb", "platform-tools", self._env, self._home)
        if adb is None:
            raise TargetError("Android Studio is not installed.")
        return adb

    def _emulator(self) -> Path | None:
        return find_tool("emulator", "emulator", self._env, self._home)

    async def _run(self, *args: str) -> str:
        try:
            return await self._runner([str(self._adb()), *args], self._home)
        except CommandError as error:
            raise TargetError(error.stderr.strip() or str(error)) from None

    async def _shell(self, serial: str, *args: str) -> str:
        return await self._run("-s", serial, "shell", *args)

    async def available(self) -> Availability:
        if find_tool("adb", "platform-tools", self._env, self._home) is None:
            return Availability(
                kind="android",
                ready=False,
                reason="Android Studio is not installed.",
                link=STUDIO_LINK,
            )
        return Availability(kind="android", ready=True)

    async def _devices(self) -> list[tuple[str, str]]:
        """Serials of online devices and their names."""
        out = await self._run("devices", "-l")
        devices: list[tuple[str, str]] = []
        for line in out.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 2 or parts[1] != "device":
                continue
            serial = parts[0]
            fields = dict(p.split(":", 1) for p in parts[2:] if ":" in p)
            name = fields.get("model", serial).replace("_", " ")
            if serial.startswith("emulator-"):
                name = await self._avd_name(serial) or name
            devices.append((serial, name))
        return devices

    async def _avd_name(self, serial: str) -> str | None:
        try:
            out = await self._run("-s", serial, "emu", "avd", "name")
        except TargetError:
            return None
        lines = [line.strip() for line in out.splitlines() if line.strip()]
        return lines[0] if lines and lines[0] != "OK" else None

    async def _avds(self) -> list[str]:
        emulator = self._emulator()
        if emulator is None:
            return []
        try:
            out = await self._runner([str(emulator), "-list-avds"], self._home)
        except CommandError:
            return []
        return [line.strip() for line in out.splitlines() if line.strip() and " " not in line]

    async def targets(self) -> list[TargetInfo]:
        if find_tool("adb", "platform-tools", self._env, self._home) is None:
            return []
        devices = await self._devices()
        running_names = {name for _, name in devices}
        found = [
            TargetInfo(key=f"android:{serial}", kind="android", name=name, running=True)
            for serial, name in devices
        ]
        found += [
            TargetInfo(key=f"android:avd:{avd}", kind="android", name=avd)
            for avd in await self._avds()
            if avd not in running_names
        ]
        return found

    async def _serial(self, key: str) -> str:
        rest = key.removeprefix("android:")
        if not rest.startswith("avd:"):
            return rest
        avd = rest.removeprefix("avd:")
        serial = await self._running_serial(avd)
        if serial is None:
            raise TargetError(f"The emulator {avd} is not running; open it first.")
        return serial

    async def open(self, key: str, url: str | None) -> TargetInfo:
        rest = key.removeprefix("android:")
        if rest.startswith("avd:"):
            avd = rest.removeprefix("avd:")
            serial = await self._running_serial(avd) or await self._start(avd)
            name = avd
        else:
            serial, name = rest, rest
            if serial not in {s for s, _ in await self._devices()}:
                raise TargetError(f"The device {serial} is not connected.")
        if url:
            await self._navigate(serial, url)
        return TargetInfo(key=f"android:{serial}", kind="android", name=name, running=True)

    async def _running_serial(self, avd: str) -> str | None:
        for serial, name in await self._devices():
            if name == avd:
                return serial
        return None

    async def _start(self, avd: str) -> str:
        emulator = self._emulator()
        if emulator is None:
            raise TargetError("The Android Emulator is not installed; add it in Android Studio.")
        if avd not in await self._avds():
            raise TargetError(f"There is no emulator named {avd}.")
        used = {serial for serial, _ in await self._devices()}
        used |= {serial for serial, s in self._started.items() if s.child.returncode is None}
        ports = range(_FIRST_PORT, _LAST_PORT, 2)
        port = next((p for p in ports if f"emulator-{p}" not in used), None)
        if port is None:
            raise TargetError("Too many emulators are running.")
        serial = f"emulator-{port}"
        child = await self._spawn(
            [str(emulator), "-avd", avd, "-no-snapshot-save", "-no-boot-anim", "-port", str(port)]
        )
        self._started[serial] = _Started(child, serial)
        await self._wait_for_boot(serial, child)
        return serial

    async def _wait_for_boot(self, serial: str, child: Child) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._boot_seconds
        while True:
            if child.returncode is not None:
                raise TargetError("The emulator stopped while starting.")
            try:
                if (await self._shell(serial, "getprop", "sys.boot_completed")).strip() == "1":
                    return
            except TargetError:
                pass
            if loop.time() >= deadline:
                raise TargetError(
                    f"The emulator did not start within {self._boot_seconds:g} seconds."
                )
            await asyncio.sleep(_POLL_SECONDS)

    async def view(self, key: str, window: str | None, screenshot: bool) -> View:
        serial = await self._serial(key)
        dump = await self._run("-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty")
        screen = parse_dump(dump)
        self._screens[serial] = screen
        image: bytes | None = None
        if screenshot:
            image = await self._screenshot(serial)
        return View(
            title=screen.title or serial,
            window=None,
            elements=screen.elements,
            truncated=screen.truncated,
            image=image,
        )

    async def _screenshot(self, serial: str) -> bytes:
        try:
            png = await self._binary(
                [str(self._adb()), "-s", serial, "exec-out", "screencap", "-p"]
            )
        except CommandError as error:
            raise TargetError(error.stderr.strip() or str(error)) from None
        original = png_size(png)
        if original is None:
            raise TargetError("The device gave no screenshot.")
        png = await self._scale(png, IMAGE_MAX)
        scaled = png_size(png) or original
        self._factors[serial] = original[0] / scaled[0]
        return png

    def _node(self, serial: str, element: str | None) -> Node:
        screen = self._screens.get(serial)
        if element is None:
            raise TargetError("Name the element to use.")
        if screen is None or element not in screen.nodes:
            raise TargetError(f"There is no element {element}; view the screen again.")
        return screen.nodes[element]

    async def act(self, key: str, action: Action) -> ActResult:
        serial = await self._serial(key)
        match action.kind:
            case "press" | "focus":
                node = self._node(serial, action.element)
                await self._shell(serial, "input", "tap", str(node.x), str(node.y))
                return ActResult(text=f"Tapped {action.element}.")
            case "click":
                if action.element is not None:
                    node = self._node(serial, action.element)
                    x, y = node.x, node.y
                else:
                    x, y = self._device_point(serial, action.x, action.y)
                await self._shell(serial, "input", "tap", str(x), str(y))
                return ActResult(text=f"Tapped at {x}, {y}.")
            case "set_value":
                return await self._set_value(serial, action)
            case "type":
                self._refuse_focused_secure(serial)
                await self._type(serial, action.text or "")
                return ActResult(text="Typed the text.")
            case "key":
                return await self._key(serial, action)
            case "scroll":
                return await self._scroll(serial, action)
            case "navigate":
                if not action.url:
                    raise TargetError("Give the address to open.")
                await self._navigate(serial, action.url)
                return ActResult(text=f"Opened {action.url}.")
            case "menu":
                raise TargetError("Android has no menu bar; press the element instead")

    def _device_point(self, serial: str, x: int | None, y: int | None) -> tuple[int, int]:
        if x is None or y is None:
            raise TargetError("Give both x and y, or an element.")
        factor = self._factors.get(serial)
        if factor is None:
            raise TargetError("Take a screenshot first, so the point can be found.")
        return round(x * factor), round(y * factor)

    def _refuse_focused_secure(self, serial: str) -> None:
        screen = self._screens.get(serial)
        if screen and any(node.focused and node.secure for node in screen.nodes.values()):
            raise SecureFieldError("The focused field is a secret field; ask the user to type it.")

    async def _set_value(self, serial: str, action: Action) -> ActResult:
        node = self._node(serial, action.element)
        if node.secure:
            raise SecureFieldError(f"{action.element} is a secret field; ask the user to type it.")
        await self._shell(serial, "input", "tap", str(node.x), str(node.y))
        if node.value:
            await self._shell(
                serial, "input", "keyevent", "KEYCODE_MOVE_END", *["KEYCODE_DEL"] * len(node.value)
            )
        await self._type(serial, action.text or "")
        return ActResult(text=f"Set {action.element}.")

    async def _type(self, serial: str, text: str) -> None:
        for command in text_commands(text):
            await self._shell(serial, *command)

    async def _key(self, serial: str, action: Action) -> ActResult:
        name = (action.key or "").lower()
        if action.modifiers:
            raise TargetError("Android keys take no modifiers.")
        if name in KEYCODES:
            code = KEYCODES[name]
        elif len(name) == 1 and (name.isascii() and name.isalnum()):
            code = f"KEYCODE_{name.upper()}"
        else:
            raise TargetError(f"Unknown key {action.key!r}.")
        await self._shell(serial, "input", "keyevent", code)
        return ActResult(text=f"Pressed {name}.")

    async def _scroll(self, serial: str, action: Action) -> ActResult:
        screen = self._screens.get(serial)
        if action.element is not None:
            node = self._node(serial, action.element)
            x, y, span = node.x, node.y, node.height
        elif screen is not None and screen.width:
            x, y, span = screen.width // 2, screen.height // 2, screen.height
        else:
            raise TargetError("View the screen first.")
        distance = min(action.amount * span // 10, span * 8 // 10)
        dx, dy = {
            "down": (0, -distance),
            "up": (0, distance),
            "right": (-distance, 0),
            "left": (distance, 0),
        }[action.direction or "down"]
        # The finger moves against the way the content scrolls.
        start = (x - dx // 2, y - dy // 2)
        end = (x + dx // 2, y + dy // 2)
        await self._shell(serial, "input", "swipe", *(str(n) for n in (*start, *end)), "300")
        return ActResult(text=f"Scrolled {action.direction or 'down'}.")

    async def _navigate(self, serial: str, url: str) -> None:
        await self._shell(
            serial, "am", "start", "-a", "android.intent.action.VIEW", "-d", shlex.quote(url)
        )

    async def front(self, key: str) -> None:
        return None

    async def close(self) -> None:
        started, self._started = self._started, {}
        for item in started.values():
            if item.child.returncode is not None:
                continue
            with contextlib.suppress(TargetError):
                await self._run("-s", item.serial, "emu", "kill")
            try:
                async with asyncio.timeout(10):
                    await item.child.wait()
            except TimeoutError:
                if item.child.returncode is None:
                    item.child.terminate()
                    await item.child.wait()
