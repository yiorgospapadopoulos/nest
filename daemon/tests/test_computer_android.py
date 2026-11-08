"""The Android backend reads the screen right, taps where the agent meant, never types into
secret fields and stops only emulators it started (B150)."""

import struct
from collections.abc import Sequence
from pathlib import Path

import pytest

from nestd.computer.backends.android import AndroidBackend, parse_dump, text_commands
from nestd.computer.models import Action, SecureFieldError

DUMP = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation="0">
<node index="0" text="" resource-id="" class="android.widget.FrameLayout"
 package="com.example.login" content-desc="" clickable="false" enabled="true"
 focused="false" scrollable="false" password="false" bounds="[0,0][1080,2400]">
  <node index="0" text="" resource-id="com.example.login:id/url_bar" class="android.widget.EditText"
   package="com.example.login" content-desc="" hint="Search or type URL" clickable="true"
   enabled="true" focused="false" scrollable="false" password="false" bounds="[40,100][1040,200]" />
  <node index="1" text="me@example.com" resource-id="com.example.login:id/email"
   class="android.widget.EditText" package="com.example.login" content-desc="Email"
   clickable="true" enabled="true" focused="false" scrollable="false" password="false"
   bounds="[40,300][1040,400]" />
  <node index="2" text="••••••" resource-id="com.example.login:id/password"
   class="android.widget.EditText" package="com.example.login" content-desc="Password"
   clickable="true" enabled="true" focused="true" scrollable="false" password="true"
   bounds="[40,500][1040,600]" />
  <node index="3" text="Sign in" resource-id="" class="android.widget.Button"
   package="com.example.login" content-desc="" clickable="true" enabled="false"
   focused="false" scrollable="false" password="false" bounds="[40,700][1040,800]" />
</node>
</hierarchy>
UI hierchary dumped to: /dev/tty
"""


def png(width: int, height: int) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I4sII", 13, b"IHDR", width, height) + b"rest"


class FakeChild:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None

    def terminate(self) -> None:
        self.returncode = -15

    async def wait(self) -> int:
        self.returncode = 0 if self.returncode is None else self.returncode
        return self.returncode


class FakeAdb:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.devices = ["emulator-5554"]

    async def __call__(self, argv: Sequence[str], cwd: Path) -> str:
        args = tuple(argv[1:])
        self.calls.append(args)
        if args[:1] == ("-list-avds",):
            return "Pixel_8\nTablet\n"
        if args[:2] == ("devices", "-l"):
            rows = [f"{s}\tdevice product:sdk model:sdk_{s[-4:]}" for s in self.devices]
            return "List of devices attached\n" + "\n".join(rows) + "\n"
        if args[2:5] == ("emu", "avd", "name"):
            return {"emulator-5554": "Tablet\nOK\n"}.get(args[1], "Pixel_8\nOK\n")
        if "exec-out" in args:
            return DUMP
        if "getprop" in args:
            return "1\n"
        return ""

    def shell(self) -> list[tuple[str, ...]]:
        return [call[3:] for call in self.calls if call[2:3] == ("shell",)]


@pytest.fixture
def sdk(tmp_path: Path) -> dict[str, str]:
    for sub, name in (("platform-tools", "adb"), ("emulator", "emulator")):
        tool = tmp_path / "sdk" / sub / name
        tool.parent.mkdir(parents=True)
        tool.write_text("")
        tool.chmod(0o755)
    return {"PATH": "", "ANDROID_HOME": str(tmp_path / "sdk")}


def test_dump_parses_into_elements_with_secret_and_address_fields() -> None:
    screen = parse_dump(DUMP)

    by_label = {e.label: e for e in screen.elements}
    assert [e.role for e in screen.elements] == ["EditText", "EditText", "EditText", "Button"]
    assert by_label["Search or type URL"].address
    assert by_label["Email"].value == "me@example.com"
    assert not by_label["Email"].address
    secret = by_label["Password"]
    assert secret.secure
    assert secret.value == ""
    assert not by_label["Sign in"].enabled
    assert screen.nodes[by_label["Sign in"].id].x == 540
    assert (screen.width, screen.height) == (1080, 2400)


def test_text_is_escaped_for_the_device_shell() -> None:
    commands = text_commands("it's $HOME; 50%s off\nok")

    assert commands == [
        ["input", "text", "'it'\"'\"'s%s$HOME;%s50%'"],
        ["input", "text", "s%soff"],
        ["input", "keyevent", "KEYCODE_ENTER"],
        ["input", "text", "ok"],
    ]


async def test_click_maps_screenshot_pixels_back_to_the_device(sdk: dict[str, str]) -> None:
    adb = FakeAdb()

    async def binary(argv: Sequence[str]) -> bytes:
        return png(1080, 2400)

    async def scale(image: bytes, max_side: int) -> bytes:
        return png(576, 1280)

    backend = AndroidBackend(runner=adb, binary=binary, scale=scale, env=sdk)
    view = await backend.view("android:emulator-5554", None, screenshot=True)
    await backend.act("android:emulator-5554", Action(kind="click", x=288, y=640))

    assert view.image == png(576, 1280)
    assert adb.shell()[-1] == ("input", "tap", "540", "1200")


async def test_secret_fields_are_never_typed_into(sdk: dict[str, str]) -> None:
    adb = FakeAdb()
    backend = AndroidBackend(runner=adb, env=sdk)
    view = await backend.view("android:emulator-5554", None, screenshot=False)
    secret = next(e for e in view.elements if e.secure)

    with pytest.raises(SecureFieldError):
        await backend.act(
            "android:emulator-5554", Action(kind="set_value", element=secret.id, text="hunter2")
        )
    # The secret field is focused, so plain typing is refused too.
    with pytest.raises(SecureFieldError):
        await backend.act("android:emulator-5554", Action(kind="type", text="hunter2"))
    assert not [call for call in adb.shell() if "text" in call]


async def test_close_stops_only_the_emulator_it_started(sdk: dict[str, str]) -> None:
    adb = FakeAdb()
    started: list[FakeChild] = []

    async def spawn(argv: Sequence[str]) -> FakeChild:
        adb.devices.append(f"emulator-{argv[-1]}")
        started.append(FakeChild(4242))
        return started[-1]

    backend = AndroidBackend(runner=adb, spawn=spawn, env=sdk)
    targets = {t.key for t in await backend.targets()}
    info = await backend.open("android:avd:Pixel_8", None)
    await backend.close()

    assert targets == {"android:emulator-5554", "android:avd:Pixel_8"}
    assert info.key == "android:emulator-5556"
    kills = [call for call in adb.calls if call[2:] == ("emu", "kill")]
    assert kills == [("-s", "emulator-5556", "emu", "kill")]
    assert started[0].returncode is not None
