"""Mocked model servers (B106): never a real one. A `Network` answers for the servers it
has, by `host:port`; any other address, or a server that is down, cannot be reached.
"""

import json
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx
from pydantic import JsonValue

from nestd.local.discovery import ModelFolders
from nestd.local.service import LocalSetup

type Answer = httpx.Response | Callable[[httpx.Request], httpx.Response]

# What an API that exists answers to an empty request: it wants a model.
NEEDS_MODEL = httpx.Response(400, json={"error": "model is required"})


class ModelServer:
    def __init__(self, port: int, host: str = "127.0.0.1") -> None:
        self.address = f"{host}:{port}"
        self.routes: dict[tuple[str, str], Answer] = {}
        self.requests: list[httpx.Request] = []
        self.down = False

    def on(self, method: str, path: str, answer: Answer) -> "ModelServer":
        self.routes[(method, path)] = answer
        return self

    def models(self, *entries: JsonValue) -> "ModelServer":
        return self.on("GET", "/v1/models", httpx.Response(200, json={"data": list(entries)}))

    def apis(self, *paths: str) -> "ModelServer":
        for path in paths:
            self.on("POST", path, NEEDS_MODEL)
        return self

    def answer(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        found = self.routes.get((request.method, request.url.path))
        if found is None:
            return httpx.Response(404, json={"error": "not found"})
        return found if isinstance(found, httpx.Response) else found(request)

    def paths(self) -> list[str]:
        return [f"{request.method} {request.url.path}" for request in self.requests]


class Network:
    def __init__(self, *servers: ModelServer) -> None:
        self.servers = {server.address: server for server in servers}

    def add(self, server: ModelServer) -> ModelServer:
        self.servers[server.address] = server
        return server

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        server = self.servers.get(f"{request.url.host}:{request.url.port}")
        if server is None or server.down:
            msg = "connection refused"
            raise httpx.ConnectError(msg, request=request)
        return server.answer(request)


ALL_APIS = ("/v1/messages", "/v1/responses", "/v1/chat/completions")


def lm_studio(port: int = 1234) -> ModelServer:
    """LM Studio 0.4 with a coder model loaded, a small one and an embedding model."""
    server = ModelServer(port).apis(*ALL_APIS)
    server.on(
        "POST",
        "/api/v1/models/load",
        httpx.Response(200, json={"type": "llm", "instance_id": "m", "status": "loaded"}),
    )
    server.models(
        {"id": "qwen/qwen3-coder-30b", "object": "model"},
        {"id": "qwen/qwen3-4b", "object": "model"},
        {"id": "text-embedding-nomic-embed-text-v1.5", "object": "model"},
    )
    return server.on(
        "GET",
        "/api/v0/models",
        httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "qwen/qwen3-coder-30b",
                        "type": "llm",
                        "state": "loaded",
                        "max_context_length": 262144,
                        "loaded_context_length": 65536,
                        "capabilities": ["tool_use"],
                    },
                    {
                        "id": "qwen/qwen3-4b",
                        "type": "vlm",
                        "state": "not-loaded",
                        "max_context_length": 40960,
                        "capabilities": ["tool_use", "reasoning"],
                    },
                    {
                        "id": "text-embedding-nomic-embed-text-v1.5",
                        "type": "embeddings",
                        "max_context_length": 2048,
                    },
                ]
            },
        ),
    )


def ollama(port: int = 11434) -> ModelServer:
    """Ollama 0.14 with one tool model on the default 4k context and one without tools."""
    server = ModelServer(port).apis(*ALL_APIS)
    server.models({"id": "qwen3:32b"}, {"id": "gemma3:27b"}, {"id": "nomic-embed-text:latest"})
    server.on("GET", "/api/tags", httpx.Response(200, json={"models": []}))
    server.on(
        "GET",
        "/api/ps",
        httpx.Response(200, json={"models": [{"name": "gemma3:27b", "context_length": 65536}]}),
    )
    shows: dict[str, JsonValue] = {
        "qwen3:32b": {
            "capabilities": ["completion", "tools", "thinking"],
            "details": {"parameter_size": "32.8B"},
        },
        "gemma3:27b": {
            "capabilities": ["completion", "vision"],
            "details": {"parameter_size": "27.4B"},
        },
        "nomic-embed-text:latest": {"capabilities": ["embedding"], "details": {}},
    }

    def show(request: httpx.Request) -> httpx.Response:
        name = json.loads(request.content)["model"]
        found = shows.get(name)
        return httpx.Response(404) if found is None else httpx.Response(200, json=found)

    return server.on("POST", "/api/show", show)


def llama_cpp(port: int = 9931) -> ModelServer:
    server = ModelServer(port).apis("/v1/messages", "/v1/chat/completions")
    server.models({"id": "Qwen3-14B-Q4_K_M.gguf"})
    return server.on(
        "GET",
        "/props",
        httpx.Response(
            200,
            json={"default_generation_settings": {"n_ctx": 32768}, "modalities": {"vision": True}},
        ),
    )


def mlx(port: int = 8080) -> ModelServer:
    """mlx-lm: Chat Completions only, nothing but the model list."""
    server = ModelServer(port).apis("/v1/chat/completions")
    return server.models({"id": "mlx-community/Qwen3-32B-4bit"})


class LocalMac:
    """What local models reach in a test: a mocked network, model folders under `root`,
    the apps installed and the commands launched, recorded instead of run.
    """

    def __init__(self, root: Path) -> None:
        self.network = Network()
        self.installed: dict[str, str] = {}
        self.launched: list[list[str]] = []
        # This Mac's memory: 24 GB.
        self.memory = 24 * 1024**3
        self.folders = ModelFolders(
            lmstudio_models=root / "lmstudio" / "models",
            lms=root / "lmstudio" / "bin" / "lms",
            ollama_models=root / "ollama",
            huggingface_hub=root / "hf",
            llama_cpp=root / "llama.cpp",
        )

    def setup(self) -> LocalSetup:
        return LocalSetup(
            self.folders,
            self.network.transport(),
            self.installed.get,
            self._launch,
            lambda: self.memory,
        )

    async def _launch(self, command: Sequence[str]) -> None:
        self.launched.append(list(command))
