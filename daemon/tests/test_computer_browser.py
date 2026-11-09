"""The browser backend reads a page's accessibility tree, clicks where the agent meant,
never types into secret fields and stops only the browser it started (B150)."""

import json
from collections.abc import AsyncGenerator, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest
from websockets.asyncio.server import ServerConnection, serve

from nestd.computer.backends.browser import BrowserBackend, map_ax_tree
from nestd.computer.models import Action, SecureFieldError

type Json = dict[str, Any]


def ax(node_id: int, role: str, name: str = "", **extra: object) -> Json:
    node: Json = {
        "nodeId": str(node_id),
        "ignored": False,
        "role": {"type": "role", "value": role},
        "name": {"type": "computedString", "value": name},
        "backendDOMNodeId": 100 + node_id,
    }
    node.update(extra)
    return node


TREE: list[Json] = [
    ax(1, "RootWebArea", "Sign in", childIds=["2", "3"]),
    ax(2, "generic", childIds=["4", "5", "6"]),
    {"nodeId": "3", "ignored": True, "role": {"type": "role", "value": "none"}},
    ax(4, "textbox", "Email", parentId="2", value={"type": "string", "value": "me@example.com"}),
    ax(
        5,
        "textbox",
        "Password",
        parentId="2",
        value={"type": "string", "value": "hunter2"},
        properties=[{"name": "focused", "value": {"type": "boolean", "value": True}}],
    ),
    ax(6, "button", "Continue", parentId="2", childIds=["7"]),
    ax(7, "StaticText", "Continue", parentId="6"),
]
for _node in TREE[1:]:
    _node.setdefault("parentId", "1")
ATTRIBUTES: dict[int, list[str]] = {104: ["type", "email"], 105: ["type", "password"]}


def test_ax_tree_maps_to_elements_and_marks_secrets() -> None:
    mapped = map_ax_tree(TREE, secure_ids={105}, address_ids=set())

    assert mapped.title == "Sign in"
    assert [(e.role, e.label, e.depth) for e in mapped.elements] == [
        ("textbox", "Email", 0),
        ("textbox", "Password", 0),
        ("button", "Continue", 0),
    ]
    email, password, button = mapped.elements
    assert email.value == "me@example.com"
    assert email.field
    assert password.secure
    assert password.focused
    assert password.value == ""
    assert button.actions == ("press",)
    assert mapped.refs[button.id].backend_id == 106


class FakeCdp:
    """Answers the DevTools calls the backend makes and records them."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Json]] = []

    async def handle(self, socket: ServerConnection) -> None:
        async for raw in socket:
            message: Json = json.loads(raw)
            method, params = message["method"], message["params"]
            self.calls.append((method, params))
            await socket.send(
                json.dumps({"id": message["id"], "result": self.result(method, params)})
            )

    def result(self, method: str, params: Json) -> Json:
        match method:
            case "Accessibility.getFullAXTree":
                return {"nodes": TREE}
            case "DOM.describeNode":
                return {"node": {"attributes": ATTRIBUTES.get(params["backendNodeId"], [])}}
            case "DOM.getBoxModel":
                return {"model": {"content": [100, 200, 180, 200, 180, 240, 100, 240]}}
            case _:
                return {}

    def mouse(self) -> list[tuple[str, float, float]]:
        return [
            (p["type"], p["x"], p["y"]) for m, p in self.calls if m == "Input.dispatchMouseEvent"
        ]


@pytest.fixture
async def cdp() -> AsyncGenerator[tuple[FakeCdp, int]]:
    fake = FakeCdp()
    async with serve(fake.handle, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        yield fake, port


def devtools(ws_port: int, started: list[str] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if started is not None and not started:
            raise httpx.ConnectError("not running", request=request)
        if request.url.path == "/json/list":
            page = {
                "id": "TAB1",
                "type": "page",
                "title": "Sign in",
                "url": "https://example.com",
                "webSocketDebuggerUrl": f"ws://127.0.0.1:{ws_port}/devtools/page/TAB1",
            }
            return httpx.Response(200, json=[page, {"id": "SW", "type": "service_worker"}])
        return httpx.Response(200, json={})

    return httpx.MockTransport(handler)


def running_profile(tmp_path: Path) -> Path:
    profile = tmp_path / "browser"
    profile.mkdir()
    (profile / "DevToolsActivePort").write_text("9333\n/devtools/browser/x\n")
    return profile


async def test_press_clicks_the_centre_of_the_element(
    tmp_path: Path, cdp: tuple[FakeCdp, int]
) -> None:
    fake, port = cdp
    backend = BrowserBackend(
        running_profile(tmp_path), executable=tmp_path / "chrome", transport=devtools(port)
    )
    view = await backend.view("browser", None, screenshot=False)
    button = next(e for e in view.elements if e.label == "Continue")
    await backend.act("browser", Action(kind="press", element=button.id))

    assert view.window == "TAB1"
    assert fake.mouse() == [
        ("mouseMoved", 140, 220),
        ("mousePressed", 140, 220),
        ("mouseReleased", 140, 220),
    ]


async def test_secret_fields_are_never_typed_into(tmp_path: Path, cdp: tuple[FakeCdp, int]) -> None:
    fake, port = cdp
    backend = BrowserBackend(
        running_profile(tmp_path), executable=tmp_path / "chrome", transport=devtools(port)
    )
    view = await backend.view("browser", None, screenshot=False)
    password = next(e for e in view.elements if e.label == "Password")

    assert password.secure
    with pytest.raises(SecureFieldError):
        await backend.act("browser", Action(kind="set_value", element=password.id, text="x"))
    assert not [m for m, _ in fake.calls if m.startswith("Input.")]


class FakeChild:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.returncode: int | None = None
        self.signals: list[str] = []

    def terminate(self) -> None:
        self.signals.append("term")
        self.returncode = -15

    def kill(self) -> None:
        self.signals.append("kill")
        self.returncode = -9

    async def wait(self) -> int:
        return self.returncode or 0


async def test_close_leaves_a_browser_it_did_not_start(
    tmp_path: Path, cdp: tuple[FakeCdp, int]
) -> None:
    _, port = cdp
    spawned: list[Sequence[str]] = []

    async def spawn(argv: Sequence[str]) -> FakeChild:
        spawned.append(argv)
        return FakeChild(1)

    backend = BrowserBackend(
        running_profile(tmp_path),
        executable=tmp_path / "chrome",
        spawn=spawn,
        transport=devtools(port),
    )
    await backend.open("browser", None)
    await backend.close()

    assert spawned == []


async def test_close_stops_the_browser_it_started_and_keeps_the_profile(
    tmp_path: Path, cdp: tuple[FakeCdp, int]
) -> None:
    _, port = cdp
    profile = tmp_path / "browser"
    up: list[str] = []
    children: list[FakeChild] = []

    async def spawn(argv: Sequence[str]) -> FakeChild:
        (profile / "DevToolsActivePort").write_text("9333\n/devtools/browser/x\n")
        up.append("yes")
        children.append(FakeChild(31337))
        return children[-1]

    backend = BrowserBackend(
        profile, executable=tmp_path / "chrome", spawn=spawn, transport=devtools(port, up)
    )
    info = await backend.open("browser", None)
    await backend.close()

    assert info.running
    assert children[0].signals == ["term"]
    assert profile.is_dir()
