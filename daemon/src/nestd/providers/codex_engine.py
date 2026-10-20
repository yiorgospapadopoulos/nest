"""What Codex reports about itself: its models and who it is signed in as (B91, D113).

A short-lived app-server is asked `model/list` and `account/read`, or for the usage windows
`account/rateLimits/read`, only: no thread, no turn, no model call, so nothing is written
to the user's Codex home.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import get_args

from pydantic import JsonValue

from nestd import __version__
from nestd.config.models import Effort
from nestd.providers.base import AccountInfo, ModelOption, UsageInfo
from nestd.providers.codex_items import items, obj, text
from nestd.providers.codex_limits import read_usage
from nestd.providers.codex_process import CodexLaunch, TransportFactory
from nestd.providers.codex_rpc import CodexRpc, JsonObject

FETCH_TIMEOUT = timedelta(seconds=60)
# The pages of `model/list` read at most, should a cursor never end.
MAX_PAGES = 20
# The model a chat without a model uses: Codex's own default (`model` left out).
DEFAULT_MODEL = "default"
NOT_SIGNED_IN = (
    "Codex isn't signed in. Sign in under Settings > Accounts on the Mac, or run `codex login`."
)
_EFFORTS: frozenset[str] = frozenset(get_args(Effort))
_PLANS = {
    "free": "ChatGPT Free",
    "go": "ChatGPT Go",
    "plus": "ChatGPT Plus",
    "pro": "ChatGPT Pro",
    "team": "ChatGPT Team",
    "business": "ChatGPT Business",
    "enterprise": "ChatGPT Enterprise",
    "edu": "ChatGPT Edu",
}


@dataclass(frozen=True)
class CodexLogin:
    """Whether Codex can run turns: signed in, or set up with a provider needing no login."""

    signed_in: bool
    account: AccountInfo


@dataclass(frozen=True)
class CodexDetails:
    models: list[ModelOption]
    login: CodexLogin


class CodexFetchError(Exception):
    """Codex could not be asked; the message never quotes what it printed."""


async def initialize(rpc: CodexRpc) -> None:
    """The handshake every connection starts with; stable API only (no experimental)."""
    await rpc.request(
        "initialize",
        {
            "clientInfo": {"name": "nest", "title": "Nest", "version": __version__},
            "capabilities": {"experimentalApi": False, "requestAttestation": False},
        },
    )
    await rpc.notify("initialized", {})


async def read_login(rpc: CodexRpc) -> CodexLogin:
    return codex_login(await rpc.request("account/read", {"refreshToken": False}))


def codex_login(response: JsonObject) -> CodexLogin:
    account = obj(response.get("account"))
    requires_auth = response.get("requiresOpenaiAuth") is not False
    kind = account.get("type")
    if kind == "chatgpt":
        plan = text(account.get("planType"))
        info = AccountInfo(
            email=text(account.get("email")) or None,
            plan=_PLANS.get(plan, f"ChatGPT {plan.capitalize()}" if plan else "ChatGPT"),
        )
    elif kind == "apiKey":
        info = AccountInfo(plan="OpenAI API key")
    elif kind == "amazonBedrock":
        info = AccountInfo(plan="Amazon Bedrock")
    else:
        info = AccountInfo()
    return CodexLogin(signed_in=bool(account) or not requires_auth, account=info)


async def read_models(rpc: CodexRpc) -> list[ModelOption]:
    models: list[ModelOption] = []
    cursor: JsonValue = None
    for _ in range(MAX_PAGES):
        page = await rpc.request("model/list", {"includeHidden": False, "cursor": cursor})
        models.extend(codex_models(page))
        cursor = page.get("nextCursor")
        if not isinstance(cursor, str):
            break
    return models


def codex_models(page: JsonObject) -> list[ModelOption]:
    """The listed models in Codex's order, Nest's thinking levels only, hidden ones left out,
    after a `default` entry for Codex's own default model, as Claude's list has (D038).
    """
    options: list[ModelOption] = []
    default: ModelOption | None = None
    for entry in items(page.get("data")):
        model = obj(entry)
        value = text(model.get("model")) or text(model.get("id"))
        if not value or model.get("hidden") is True:
            continue
        levels = [
            level
            for option in items(model.get("supportedReasoningEfforts"))
            if (level := text(obj(option).get("reasoningEffort"))) in _EFFORTS
        ]
        option = ModelOption(
            value=value,
            display_name=text(model.get("displayName")) or value,
            description=text(model.get("description")),
            effort_levels=levels,
            supports_effort=bool(levels),
            # Nest's Auto mode runs Codex with its own approval reviewer.
            supports_auto_mode=True,
            resolved_model=value,
        )
        options.append(option)
        if model.get("isDefault") is True and default is None:
            default = option.model_copy(
                update={
                    "value": DEFAULT_MODEL,
                    "display_name": f"Default ({option.display_name})",
                    "description": "Codex's default model",
                }
            )
    return [default, *options] if default is not None else options


async def fetch_codex(
    factory: TransportFactory, launch: CodexLaunch, time_limit: timedelta = FETCH_TIMEOUT
) -> CodexDetails:
    async def ask(rpc: CodexRpc) -> CodexDetails:
        return CodexDetails(await read_models(rpc), await read_login(rpc))

    return await ask_codex(factory, launch, ask, time_limit)


async def fetch_codex_usage(
    factory: TransportFactory, launch: CodexLaunch, time_limit: timedelta = FETCH_TIMEOUT
) -> UsageInfo | None:
    """Codex's usage windows from a short-lived server; None when it reports none."""
    return await ask_codex(factory, launch, read_usage, time_limit)


async def ask_codex[T](
    factory: TransportFactory,
    launch: CodexLaunch,
    ask: Callable[[CodexRpc], Awaitable[T]],
    time_limit: timedelta = FETCH_TIMEOUT,
) -> T:
    """`ask` on a short-lived app-server, closed after; CodexFetchError names only the
    kind of failure.
    """

    async def ignore(_method: str, _params: JsonObject) -> None:
        return None

    async def refuse(_method: str, _params: JsonObject) -> JsonValue:
        return {}

    try:
        async with asyncio.timeout(time_limit.total_seconds()):
            rpc = CodexRpc(await factory(launch), ignore, refuse)
            try:
                await initialize(rpc)
                return await ask(rpc)
            finally:
                await rpc.close()
    except TimeoutError as error:
        msg = "timed out"
        raise CodexFetchError(msg) from error
    except Exception as error:
        # Codex's errors can quote what it printed; only their kind is kept.
        raise CodexFetchError(type(error).__name__) from error
