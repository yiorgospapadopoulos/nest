"""B106, live: LM Studio loads a model on first use with its own default context (8192 for
gpt-oss-20b), too little for an agent, so Nest loads it first with enough.
"""

import json
from collections.abc import AsyncIterator

import httpx
import pytest

from nestd.local.loading import AGENT_CONTEXT, LoadError, ensure_loaded
from tests.local_support import ModelServer, Network, lm_studio

BASE = "http://127.0.0.1:1234"


def loads(server: ModelServer) -> list[dict[str, object]]:
    return [
        json.loads(request.content)
        for request in server.requests
        if request.url.path == "/api/v1/models/load"
    ]


def loaded_with(server: ModelServer, model: str, context: int) -> None:
    server.on(
        "GET",
        "/api/v0/models",
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": model,
                        "state": "loaded",
                        "max_context_length": 131072,
                        "loaded_context_length": context,
                    }
                ]
            },
        ),
    )


@pytest.fixture
def server() -> ModelServer:
    return lm_studio()


@pytest.fixture
async def client(server: ModelServer) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=Network(server).transport()) as http:
        yield http


async def test_a_model_not_loaded_is_loaded_with_as_much_as_it_takes_up_to_64k(
    server: ModelServer, client: httpx.AsyncClient
) -> None:
    context = await ensure_loaded(client, BASE, "sk", "qwen/qwen3-4b")

    assert context == 40960
    assert loads(server) == [{"model": "qwen/qwen3-4b", "context_length": 40960}]
    load = next(r for r in server.requests if r.url.path == "/api/v1/models/load")
    assert load.headers["authorization"] == "Bearer sk"
    assert AGENT_CONTEXT == 65536


async def test_the_caller_hears_when_a_load_starts_and_only_then(
    server: ModelServer, client: httpx.AsyncClient
) -> None:
    started: list[int] = []

    async def on_load() -> None:
        # Before the load: LM Studio has not been asked yet.
        started.append(len([r for r in server.requests if r.url.path.endswith("/load")]))

    await ensure_loaded(client, BASE, None, "qwen/qwen3-4b", on_load)
    await ensure_loaded(client, BASE, None, "qwen/qwen3-coder-30b", on_load)

    assert started == [0]


async def test_a_model_loaded_with_enough_is_left_as_it_is(
    server: ModelServer, client: httpx.AsyncClient
) -> None:
    assert await ensure_loaded(client, BASE, None, "qwen/qwen3-coder-30b") == 65536
    assert loads(server) == []


async def test_a_model_loaded_with_too_little_is_loaded_again_with_enough(
    server: ModelServer, client: httpx.AsyncClient
) -> None:
    loaded_with(server, "openai/gpt-oss-20b", 8192)

    assert await ensure_loaded(client, BASE, None, "openai/gpt-oss-20b") == 65536
    assert loads(server) == [{"model": "openai/gpt-oss-20b", "context_length": 65536}]


@pytest.mark.parametrize("listing", [httpx.Response(500), httpx.Response(200, content=b"not json")])
async def test_a_model_lm_studio_does_not_list_is_loaded_with_64k(
    server: ModelServer, client: httpx.AsyncClient, listing: httpx.Response
) -> None:
    server.on("GET", "/api/v0/models", listing)

    assert await ensure_loaded(client, BASE, None, "new/model") == 65536
    assert loads(server) == [{"model": "new/model", "context_length": 65536}]


async def test_a_failed_load_says_so(server: ModelServer, client: httpx.AsyncClient) -> None:
    server.on(
        "POST", "/api/v1/models/load", httpx.Response(500, json={"error": "not enough memory"})
    )

    with pytest.raises(LoadError, match="not enough memory"):
        await ensure_loaded(client, BASE, None, "qwen/qwen3-4b")


async def test_a_load_that_cannot_be_asked_fails_too(
    server: ModelServer, client: httpx.AsyncClient
) -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    server.on("POST", "/api/v1/models/load", broken)

    with pytest.raises(LoadError, match="slow"):
        await ensure_loaded(client, BASE, None, "qwen/qwen3-4b")
