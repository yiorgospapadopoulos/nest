"""LM Studio models loaded with enough context before a run (B106).

LM Studio loads a model on its first request with the model's own default context (8192
for gpt-oss-20b, live), which Claude Code's first request (about 20k tokens) does not fit.
So before a run Nest reads `/api/v0/models` and, when the model is not loaded or loaded
with less than it needs, loads it through `POST /api/v1/models/load` with 64k, or the
model's whole context when that is less. Nothing is ever unloaded.
"""

from collections.abc import Awaitable, Callable

import httpx
from pydantic import JsonValue

from nestd.local.probe import TIMEOUT, auth_headers
from nestd.providers.codex_items import items, obj, text

# What an agent needs: its first request alone is about 20 thousand tokens.
AGENT_CONTEXT = 65536
# Loading a big model from disk takes a while (6.5 s for gpt-oss-20b, live).
LOAD_TIMEOUT = httpx.Timeout(300.0, connect=5.0)


class LoadError(Exception):
    """LM Studio did not load the model; the message says why."""


async def ensure_loaded(
    client: httpx.AsyncClient,
    base_url: str,
    key: str | None,
    model: str,
    on_load: Callable[[], Awaitable[None]] | None = None,
) -> int:
    """The context the model is loaded with now, after loading it when needed; `on_load`
    hears that a load starts.
    """
    headers = auth_headers(key)
    entry = await _entry(client, base_url, headers, model)
    largest = _number(entry.get("max_context_length"))
    needed = min(AGENT_CONTEXT, largest or AGENT_CONTEXT)
    loaded = _number(entry.get("loaded_context_length"))
    if text(entry.get("state")) == "loaded" and loaded is not None and loaded >= needed:
        return loaded
    if on_load is not None:
        await on_load()
    try:
        answer = await client.post(
            f"{base_url}/api/v1/models/load",
            json={"model": model, "context_length": needed},
            headers=headers,
            timeout=LOAD_TIMEOUT,
        )
    except httpx.HTTPError as error:
        raise LoadError(str(error) or type(error).__name__) from error
    if not answer.is_success:
        raise LoadError(answer.text.strip() or f"HTTP {answer.status_code}")
    return needed


async def _entry(
    client: httpx.AsyncClient, base_url: str, headers: dict[str, str], model: str
) -> dict[str, JsonValue]:
    """The model's entry in LM Studio's list; empty when it is not there."""
    try:
        answer = await client.get(f"{base_url}/api/v0/models", headers=headers, timeout=TIMEOUT)
        listed: JsonValue = answer.json() if answer.is_success else None
    except (httpx.HTTPError, ValueError):
        listed = None
    for raw in items(obj(listed).get("data")):
        entry = obj(raw)
        if text(entry.get("id")) == model:
            return entry
    return {}


def _number(value: JsonValue | None) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None
