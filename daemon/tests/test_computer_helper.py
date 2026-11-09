"""The daemon's side of the Nest Computer helper (B150): it starts the helper when nothing
listens, matches replies to requests and passes the helper's refusals on."""

import asyncio
import json
import tempfile
from collections.abc import AsyncIterator, Sequence
from pathlib import Path

import pytest

from nestd.computer.helper import Helper, HelperError, socket_path


class FakeHelperApp:
    """Listens on the socket once launched, answering like the real helper."""

    def __init__(self, socket: Path) -> None:
        self.socket = socket
        self.launches: list[list[str]] = []
        self.server: asyncio.Server | None = None

    async def launch(self, _app: Path, args: Sequence[str]) -> None:
        self.launches.append(list(args))
        self.server = await asyncio.start_unix_server(self._serve, path=str(self.socket))

    async def _serve(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        requests = [json.loads(await reader.readline()) for _ in range(2)]
        # Answered out of order: replies go by id.
        for request in reversed(requests):
            writer.write((json.dumps(self._reply(request)) + "\n").encode())
        await writer.drain()
        if any(r["op"] == "quit" for r in requests):
            writer.close()

    def _reply(self, request: dict[str, object]) -> dict[str, object]:
        if request["op"] == "set_value":
            error = {"code": "secure_field", "message": "That is a password field."}
            return {"id": request["id"], "ok": False, "error": error}
        if request["op"] == "screenshot":
            # A real screenshot's base64 PNG is megabytes on one line.
            return {"id": request["id"], "ok": True, "result": {"png": "A" * 3_000_000}}
        return {"id": request["id"], "ok": True, "result": {"op": request["op"]}}


@pytest.fixture
async def app() -> AsyncIterator[FakeHelperApp]:
    # Unix socket paths have a short limit; pytest's own folders are too long on macOS.
    with tempfile.TemporaryDirectory(dir="/tmp") as folder:
        fake = FakeHelperApp(Path(folder) / "h.sock")
        yield fake
        if fake.server is not None:
            fake.server.close()


def helper_for(app: FakeHelperApp, tmp_path: Path) -> Helper:
    bundle = tmp_path / "Nest Computer.app"
    bundle.mkdir()
    return Helper(bundle, app.socket, launcher=app.launch)


async def test_it_starts_the_helper_and_matches_replies_by_id(
    app: FakeHelperApp, tmp_path: Path
) -> None:
    helper = helper_for(app, tmp_path)

    first, second = await asyncio.gather(helper.call("apps"), helper.call("hello"))

    assert (first, second) == ({"op": "apps"}, {"op": "hello"})
    assert app.launches[0][:2] == ["--socket", str(app.socket)]
    assert app.launches[0][2] == "--controller"
    await helper.close()


async def test_a_refusal_keeps_its_code(app: FakeHelperApp, tmp_path: Path) -> None:
    helper = helper_for(app, tmp_path)

    results = await asyncio.gather(
        helper.call("set_value", {"element": "e1", "text": "x"}),
        helper.call("hello"),
        return_exceptions=True,
    )

    refused = results[0]
    assert isinstance(refused, HelperError)
    assert (refused.code, str(refused)) == ("secure_field", "That is a password field.")
    await helper.close()


async def test_a_screenshot_reply_of_megabytes_comes_through(
    app: FakeHelperApp, tmp_path: Path
) -> None:
    helper = helper_for(app, tmp_path)

    shot, _ = await asyncio.gather(helper.call("screenshot"), helper.call("hello"))

    assert len(str(shot["png"])) == 3_000_000
    await helper.close()


async def test_without_the_helper_app_nothing_starts(app: FakeHelperApp, tmp_path: Path) -> None:
    helper = Helper(tmp_path / "missing.app", app.socket, launcher=app.launch)

    with pytest.raises(HelperError, match="not installed"):
        await helper.call("hello")
    assert app.launches == []


def test_a_long_data_folder_gets_a_short_socket(tmp_path: Path) -> None:
    short = socket_path(Path("/Users/me/Library/Application Support/nest"))
    long = socket_path(tmp_path / ("x" * 120))

    assert short == Path("/Users/me/Library/Application Support/nest/computer/helper.sock")
    assert str(long).startswith("/tmp/nest-")  # noqa: S108
    assert len(str(long)) < 100
