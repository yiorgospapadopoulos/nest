import io
import logging
from collections.abc import Iterator
from typing import ClassVar

import pytest
import uvicorn
from fastapi import FastAPI

from harness.logging_setup import configure_logging
from harness.server import HOST, run_uvicorn


@pytest.fixture
def restore_logging() -> Iterator[None]:
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


@pytest.mark.usefixtures("restore_logging")
def test_logging_goes_to_the_given_stream_in_a_concise_format() -> None:
    stream = io.StringIO()

    configure_logging(stream)
    logging.getLogger("harness.test").info("hello %s", "world")
    logging.getLogger("harness.test").debug("hidden")

    line = stream.getvalue()
    assert line.endswith(" INFO harness.test: hello world\n")
    assert "hidden" not in line


class FakeServer:
    instances: ClassVar[list["FakeServer"]] = []

    def __init__(self, config: uvicorn.Config) -> None:
        self.config = config
        self.served = False
        FakeServer.instances.append(self)

    async def serve(self) -> None:
        self.served = True


async def test_uvicorn_serves_on_localhost_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uvicorn, "Server", FakeServer)
    app = FastAPI()

    await run_uvicorn(app, 9123)

    (server,) = FakeServer.instances
    assert server.served is True
    assert server.config.app is app
    assert server.config.host == HOST == "127.0.0.1"
    assert server.config.port == 9123
    assert server.config.lifespan == "on"
    assert server.config.log_config is None
