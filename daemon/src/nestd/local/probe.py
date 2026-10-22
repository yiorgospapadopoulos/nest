"""What a model server is and serves (B106), asked without making a model generate.

Its model list comes from `/v1/models`. Which APIs it answers is found by posting an empty
object to each: 404 or 405 means missing, anything else (400, 422...) present. The app is
told by cheap signals: LM Studio answers `/api/v0/models` (context, tool use and vision per
model), Ollama `/api/tags` (`/api/show` per model gives its tools, vision, thinking and
size, `/api/ps` the context of a loaded one), llama.cpp `/props`. Embedding models are left
out: they cannot chat.
"""

import asyncio
import re
from dataclasses import dataclass, replace
from urllib.parse import urlsplit

import httpx
from pydantic import JsonValue

from nestd.errors import InvalidInputError
from nestd.providers.codex_items import items, obj, text

TIMEOUT = httpx.Timeout(2.0)
MESSAGES = "/v1/messages"
RESPONSES = "/v1/responses"
CHAT = "/v1/chat/completions"
_MISSING = frozenset({404, 405})
# Ollama runs every model with this context unless told otherwise (on Macs under 24 GiB).
OLLAMA_DEFAULT_CONTEXT = 4096
_SIZE = re.compile(r"^(\d+(?:\.\d+)?)\s*[Bb]$")
_HOST = re.compile(r"^[A-Za-z0-9.-]+$|^\[[0-9A-Fa-f:.]+\]$")


@dataclass(frozen=True)
class ServerAddress:
    # `host:port`, as stored.
    address: str
    base_url: str


@dataclass(frozen=True)
class ProbedModel:
    model: str
    context: int | None
    # Billions of parameters, when the server says.
    params: float | None
    # Whether the server says the model calls tools; None when it does not say.
    tools: bool | None
    vision: bool
    thinking: bool
    # Bytes on disk, which loading takes in memory, when the server says.
    size: int | None = None


@dataclass(frozen=True)
class ProbedServer:
    address: ServerAddress
    app: str | None
    messages: bool
    responses: bool
    chat: bool
    models: tuple[ProbedModel, ...]


@dataclass(frozen=True)
class _Details:
    context: int | None = None
    params: float | None = None
    tools: bool | None = None
    vision: bool = False
    thinking: bool = False
    embedding: bool = False
    size: int | None = None


def normalise(typed: str) -> ServerAddress:
    """`host:port` and the base URL from what the user typed: a scheme, a path such as
    `/v1` and a trailing slash may be given; 422 for anything else.
    """
    raw = typed.strip()
    if raw and "://" not in raw:
        raw = f"http://{raw}"
    try:
        parts = urlsplit(raw)
        port = parts.port
    except ValueError as error:
        raise InvalidInputError(f"not a server address: {typed!r}") from error
    netloc = parts.netloc.rsplit("@", 1)[-1]
    host = netloc.rsplit(":", 1)[0] if port is not None else netloc
    if parts.scheme not in ("http", "https") or not host or _HOST.fullmatch(host) is None:
        raise InvalidInputError(f"not a server address: {typed!r}")
    host = host.lower()
    port = port or (443 if parts.scheme == "https" else 80)
    return ServerAddress(f"{host}:{port}", f"{parts.scheme}://{host}:{port}")


def auth_headers(key: str | None) -> dict[str, str]:
    """A server's key the way either kind of API takes it."""
    return {} if key is None else {"Authorization": f"Bearer {key}", "x-api-key": key}


async def reachable(client: httpx.AsyncClient, base_url: str, key: str | None) -> bool:
    try:
        await client.get(f"{base_url}/v1/models", headers=auth_headers(key), timeout=TIMEOUT)
    except httpx.HTTPError:
        return False
    return True


async def probe(
    client: httpx.AsyncClient, where: ServerAddress, key: str | None
) -> ProbedServer | None:
    """None when the server cannot be reached."""
    headers = auth_headers(key)
    base = where.base_url
    try:
        listing = await client.get(f"{base}/v1/models", headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError:
        return None
    entries = _listed(listing)
    messages, responses, chat = await asyncio.gather(
        *(_answers(client, base + path, headers) for path in (MESSAGES, RESPONSES, CHAT))
    )
    app, details = await _app(client, base, headers, [entry_id for entry_id, _ in entries])
    models: list[ProbedModel] = []
    for model, entry in entries:
        found = details.get(model) or _generic(entry)
        if found.embedding or "embed" in model.lower():
            continue
        models.append(
            ProbedModel(
                model,
                found.context,
                found.params,
                found.tools,
                found.vision,
                found.thinking,
                found.size,
            )
        )
    if app is None and any(text(entry.get("owned_by")) == "vllm" for _, entry in entries):
        app = "vLLM"
    return ProbedServer(where, app, messages, responses, chat, tuple(models))


async def _answers(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> bool:
    try:
        response = await client.post(url, json={}, headers=headers, timeout=TIMEOUT)
    except httpx.HTTPError:
        return False
    return response.status_code not in _MISSING


def _listed(response: httpx.Response) -> list[tuple[str, dict[str, JsonValue]]]:
    entries: list[tuple[str, dict[str, JsonValue]]] = []
    for raw in items(obj(_json(response)).get("data")):
        entry = obj(raw)
        model = text(entry.get("id"))
        if model:
            entries.append((model, entry))
    return entries


def _generic(entry: dict[str, JsonValue]) -> _Details:
    """What an OpenAI-style list entry tells: vLLM's `max_model_len`, other servers'
    `context_length`, llama.cpp's training context.
    """
    context = (
        _number(entry.get("max_model_len"))
        or _number(entry.get("context_length"))
        or _number(obj(entry.get("meta")).get("n_ctx_train"))
    )
    return _Details(context=context)


async def _app(
    client: httpx.AsyncClient, base: str, headers: dict[str, str], models: list[str]
) -> tuple[str | None, dict[str, _Details]]:
    lm_studio = await _get(client, f"{base}/api/v0/models", headers)
    if lm_studio is not None:
        sizes = _sizes(await _get(client, f"{base}/api/v1/models", headers), "key", "size_bytes")
        return "LM Studio", {
            model: replace(found, size=sizes.get(model))
            for model, found in _lm_studio(lm_studio).items()
        }
    tags = await _get(client, f"{base}/api/tags", headers)
    if tags is not None:
        sizes = _sizes(tags, "name", "size")
        return "Ollama", {
            model: replace(found, size=sizes.get(model))
            for model, found in (await _ollama(client, base, headers, models)).items()
        }
    props = await _get(client, f"{base}/props", headers)
    if props is not None:
        return "llama.cpp", dict.fromkeys(models, _llama_cpp(props))
    return None, {}


def _sizes(answer: JsonValue | None, name: str, size: str) -> dict[str, int]:
    """Each listed model's size: LM Studio's `/api/v1/models`, Ollama's `/api/tags`."""
    found: dict[str, int] = {}
    for raw in items(obj(answer).get("models")):
        entry = obj(raw)
        value = _number(entry.get(size))
        if value is not None:
            found[text(entry.get(name))] = value
    return found


def _lm_studio(answer: JsonValue) -> dict[str, _Details]:
    details: dict[str, _Details] = {}
    for raw in items(obj(answer).get("data")):
        entry = obj(raw)
        capabilities = entry.get("capabilities")
        listed = [text(c) for c in items(capabilities)]
        kind = text(entry.get("type"))
        details[text(entry.get("id"))] = _Details(
            context=_number(entry.get("loaded_context_length"))
            or _number(entry.get("max_context_length")),
            tools=None if capabilities is None else "tool_use" in listed,
            vision=kind == "vlm",
            thinking="reasoning" in listed,
            embedding=kind == "embeddings",
        )
    return details


async def _ollama(
    client: httpx.AsyncClient, base: str, headers: dict[str, str], models: list[str]
) -> dict[str, _Details]:
    running = await _get(client, f"{base}/api/ps", headers)
    contexts = {
        text(obj(entry).get("name")): _number(obj(entry).get("context_length"))
        for entry in items(obj(running).get("models"))
    }
    shown = await asyncio.gather(*(_show(client, base, headers, model) for model in models))
    return {
        model: replace(found, context=contexts.get(model) or OLLAMA_DEFAULT_CONTEXT)
        for model, found in zip(models, shown, strict=True)
    }


async def _show(
    client: httpx.AsyncClient, base: str, headers: dict[str, str], model: str
) -> _Details:
    answer = obj(await _post(client, f"{base}/api/show", headers, {"model": model}))
    capabilities = answer.get("capabilities")
    listed = [text(c) for c in items(capabilities)]
    size = _SIZE.match(text(obj(answer.get("details")).get("parameter_size")))
    return _Details(
        params=None if size is None else float(size.group(1)),
        tools=None if not isinstance(capabilities, list) else "tools" in listed,
        vision="vision" in listed,
        thinking="thinking" in listed,
        embedding="embedding" in listed and "completion" not in listed,
    )


def _llama_cpp(props: JsonValue) -> _Details:
    answer = obj(props)
    context = _number(obj(answer.get("default_generation_settings")).get("n_ctx")) or _number(
        answer.get("n_ctx")
    )
    return _Details(context=context, vision=obj(answer.get("modalities")).get("vision") is True)


async def _get(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> JsonValue | None:
    """The JSON answer, or None when there is none."""
    try:
        return _json(await client.get(url, headers=headers, timeout=TIMEOUT))
    except httpx.HTTPError:
        return None


async def _post(
    client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, JsonValue]
) -> JsonValue | None:
    try:
        return _json(await client.post(url, json=body, headers=headers, timeout=TIMEOUT))
    except httpx.HTTPError:
        return None


def _json(response: httpx.Response) -> JsonValue | None:
    if response.status_code != 200:
        return None
    try:
        value: JsonValue = response.json()
    except ValueError:
        return None
    return value


def _number(value: JsonValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
