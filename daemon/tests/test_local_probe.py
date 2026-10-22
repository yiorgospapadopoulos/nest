import json
from collections.abc import AsyncIterator

import httpx
import pytest

from nestd.errors import InvalidInputError
from nestd.local.probe import ProbedModel, ServerAddress, normalise, probe, reachable
from tests.local_support import ModelServer, Network, llama_cpp, lm_studio, mlx, ollama


@pytest.mark.parametrize(
    ("typed", "address", "base_url"),
    [
        ("127.0.0.1:1234", "127.0.0.1:1234", "http://127.0.0.1:1234"),
        ("http://localhost:11434/", "localhost:11434", "http://localhost:11434"),
        (" http://192.168.1.20:8000/v1 ", "192.168.1.20:8000", "http://192.168.1.20:8000"),
        ("https://models.example.org", "models.example.org:443", "https://models.example.org:443"),
        ("Studio.local", "studio.local:80", "http://studio.local:80"),
        ("[::1]:8080", "[::1]:8080", "http://[::1]:8080"),
    ],
)
def test_an_address_is_normalised(typed: str, address: str, base_url: str) -> None:
    assert normalise(typed) == ServerAddress(address, base_url)


@pytest.mark.parametrize("typed", ["", "ftp://host:21", "http://", "host:port", "http://a b:1"])
def test_a_bad_address_is_refused(typed: str) -> None:
    with pytest.raises(InvalidInputError):
        normalise(typed)


@pytest.fixture
def network() -> Network:
    return Network()


@pytest.fixture
async def client(network: Network) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(transport=network.transport()) as http:
        yield http


async def test_lm_studio_is_labelled_and_its_models_described(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = network.add(lm_studio())

    found = await probe(client, normalise(server.address), "s3cret")

    assert found is not None
    assert (found.app, found.messages, found.responses, found.chat) == (
        "LM Studio",
        True,
        True,
        True,
    )
    assert found.models == (
        ProbedModel("qwen/qwen3-coder-30b", 65536, None, True, False, False),
        ProbedModel("qwen/qwen3-4b", 40960, None, True, True, True),
    )
    assert {request.headers["authorization"] for request in server.requests} == {"Bearer s3cret"}
    # The APIs are asked about with an empty request, which no model answers.
    posted = [r for r in server.requests if r.method == "POST"]
    assert {r.url.path for r in posted} == {"/v1/messages", "/v1/responses", "/v1/chat/completions"}
    assert {r.content for r in posted} == {b"{}"}


async def test_ollama_reports_its_context_tools_and_sizes(
    network: Network, client: httpx.AsyncClient
) -> None:
    network.add(ollama())

    found = await probe(client, normalise("127.0.0.1:11434"), None)

    assert found is not None
    assert found.app == "Ollama"
    assert found.models == (
        # Not loaded: Ollama's default context.
        ProbedModel("qwen3:32b", 4096, 32.8, True, False, True),
        ProbedModel("gemma3:27b", 65536, 27.4, False, True, False),
    )


async def test_llama_cpp_gives_its_context_to_its_model(
    network: Network, client: httpx.AsyncClient
) -> None:
    network.add(llama_cpp())

    found = await probe(client, normalise("127.0.0.1:9931"), None)

    assert found is not None
    assert (found.app, found.messages, found.responses, found.chat) == (
        "llama.cpp",
        True,
        False,
        True,
    )
    assert found.models == (ProbedModel("Qwen3-14B-Q4_K_M.gguf", 32768, None, None, True, False),)


async def test_a_plain_server_is_unlabelled(network: Network, client: httpx.AsyncClient) -> None:
    network.add(mlx())

    found = await probe(client, normalise("127.0.0.1:8080"), None)

    assert found is not None
    assert (found.app, found.messages, found.responses, found.chat) == (None, False, False, True)
    assert found.models == (
        ProbedModel("mlx-community/Qwen3-32B-4bit", None, None, None, False, False),
    )


async def test_vllm_is_known_by_its_model_list(network: Network, client: httpx.AsyncClient) -> None:
    server = ModelServer(8000).apis("/v1/messages", "/v1/chat/completions")
    server.models(
        {"id": "Qwen/Qwen3-32B", "owned_by": "vllm", "max_model_len": 40960},
        {"id": "other", "context_length": 8192},
        {"id": "gguf", "meta": {"n_ctx_train": 16384}},
        {"no": "id"},
        "junk",
    )
    network.add(server)

    found = await probe(client, normalise("127.0.0.1:8000"), None)

    assert found is not None
    assert found.app == "vLLM"
    assert [(m.model, m.context) for m in found.models] == [
        ("Qwen/Qwen3-32B", 40960),
        ("other", 8192),
        ("gguf", 16384),
    ]


async def test_an_api_that_is_not_there_or_fails_counts_as_missing(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = ModelServer(5001).models({"id": "m"})
    server.on("POST", "/v1/messages", httpx.Response(405))
    server.on("POST", "/v1/responses", httpx.Response(422))

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    server.on("POST", "/v1/chat/completions", broken)
    network.add(server)

    found = await probe(client, normalise("127.0.0.1:5001"), None)

    assert found is not None
    assert (found.messages, found.responses, found.chat) == (False, True, False)


async def test_an_unreachable_server_gives_nothing(client: httpx.AsyncClient) -> None:
    assert await probe(client, normalise("127.0.0.1:1234"), None) is None


async def test_a_server_whose_model_list_fails_has_no_models(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = ModelServer(1234).apis("/v1/chat/completions")
    server.on("GET", "/v1/models", httpx.Response(401, json={"error": "key"}))
    network.add(server)

    found = await probe(client, normalise("127.0.0.1:1234"), None)

    assert found is not None
    assert found.models == ()


async def test_odd_answers_from_the_app_apis_are_ignored(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = ModelServer(1234).apis("/v1/chat/completions").models({"id": "a"}, {"id": "b-8b"})

    def broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    server.on("GET", "/api/v0/models", broken)
    server.on("GET", "/api/tags", httpx.Response(200, json=["not", "an", "object"]))
    server.on("GET", "/api/ps", httpx.Response(200, content=b"not json"))

    def show(request: httpx.Request) -> httpx.Response:
        name = json.loads(request.content)["model"]
        if name == "a":
            return broken(request)
        return httpx.Response(200, json={"capabilities": "tools", "details": {}})

    server.on("POST", "/api/show", show)
    network.add(server)

    found = await probe(client, normalise("127.0.0.1:1234"), None)

    assert found is not None
    assert found.app == "Ollama"
    assert found.models == (
        ProbedModel("a", 4096, None, None, False, False),
        ProbedModel("b-8b", 4096, None, None, False, False),
    )


async def test_lm_studio_entries_without_capabilities_say_nothing_of_tools(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = ModelServer(1234).apis("/v1/chat/completions").models({"id": "a"}, {"id": "b"})
    server.on(
        "GET",
        "/api/v0/models",
        httpx.Response(200, json={"data": [{"id": "a", "type": "llm"}, "junk"]}),
    )
    network.add(server)

    found = await probe(client, normalise("127.0.0.1:1234"), None)

    assert found is not None
    assert found.models == (
        ProbedModel("a", None, None, None, False, False),
        ProbedModel("b", None, None, None, False, False),
    )


async def test_a_llama_cpp_props_answer_without_settings_gives_no_context(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = ModelServer(9931).apis("/v1/chat/completions").models({"id": "m"})
    server.on("GET", "/props", httpx.Response(200, json={"n_ctx": 8192}))
    network.add(server)

    found = await probe(client, normalise("127.0.0.1:9931"), None)

    assert found is not None
    assert found.models == (ProbedModel("m", 8192, None, None, False, False),)


async def test_reachable_asks_the_model_list(network: Network, client: httpx.AsyncClient) -> None:
    server = network.add(mlx())

    assert await reachable(client, "http://127.0.0.1:8080", "k")
    assert server.requests[-1].headers["x-api-key"] == "k"
    server.down = True
    assert not await reachable(client, "http://127.0.0.1:8080", None)


async def test_lm_studio_gives_each_models_size_on_disk(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = network.add(lm_studio())
    server.on(
        "GET",
        "/api/v1/models",
        httpx.Response(
            200,
            json={
                "models": [
                    {"key": "qwen/qwen3-coder-30b", "size_bytes": 17_000_000_000},
                    {"key": "qwen/qwen3-4b", "size_bytes": "big"},
                    "junk",
                ]
            },
        ),
    )

    found = await probe(client, normalise(server.address), None)

    assert found is not None
    assert [model.size for model in found.models] == [17_000_000_000, None]


async def test_ollama_gives_each_models_size_on_disk(
    network: Network, client: httpx.AsyncClient
) -> None:
    server = network.add(ollama())
    server.on(
        "GET",
        "/api/tags",
        httpx.Response(
            200, json={"models": [{"name": "qwen3:32b", "size": 20_000_000_000}, {"name": "x"}]}
        ),
    )

    found = await probe(client, normalise(server.address), None)

    assert found is not None
    assert [model.size for model in found.models] == [20_000_000_000, None]


async def test_without_a_size_list_sizes_are_unknown(
    network: Network, client: httpx.AsyncClient
) -> None:
    network.add(lm_studio())

    found = await probe(client, normalise("127.0.0.1:1234"), None)

    assert found is not None
    assert {model.size for model in found.models} == {None}
