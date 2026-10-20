"""The engines' models and accounts, for clients' pickers and profile (D038, B91)."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from nestd.api.deps import Context, RequireDevice
from nestd.engine.models import ModelList
from nestd.providers.base import AccountInfo, ProviderFeature
from nestd.providers.codex_engine import NOT_SIGNED_IN

router = APIRouter(prefix="/api", dependencies=[RequireDevice])

type ProviderName = Literal["claude", "codex"]
CODEX = "codex"
_DISPLAY_NAMES = {"claude": "Claude", "codex": "Codex"}


class ProviderInfo(BaseModel):
    """An engine a new chat can run on (B91)."""

    # What a new chat's `provider` is set to.
    name: str
    display_name: str
    # Whether it can run chats now; None when Nest does not check (Claude) or Codex could
    # not be asked. Codex stays offered when false: its chats fail with
    # `codex_not_signed_in` until the user signs in.
    signed_in: bool | None
    # What to tell the user when `signed_in` is false.
    sign_in_hint: str | None = None
    account: AccountInfo | None = None
    # What its chats cannot do, which clients hide; refused with `unsupported_feature`.
    unsupported: list[ProviderFeature]


class ProviderList(BaseModel):
    """`GET /api/providers`: the default engine first."""

    providers: list[ProviderInfo]


@router.get("/models")
async def list_models(ctx: Context, provider: ProviderName = "claude") -> ModelList:
    """The engine's model list in its order: Claude Code's (its aliases until it reported
    one), or Codex's (empty until Codex could be asked).
    """
    if provider == CODEX:
        return await ctx.codex.models()
    return await ctx.engine.models()


@router.get("/account")
async def account(ctx: Context, provider: ProviderName = "claude") -> AccountInfo:
    """Who the engine is signed in as; all null until it reported it."""
    if provider == CODEX:
        return await ctx.codex.account()
    return await ctx.engine.account()


@router.get("/providers")
async def list_providers(ctx: Context, refresh: bool = False) -> ProviderList:
    """The engines chats can run on, with Claude's account as its engine last reported it,
    Codex's login (asked at most once a minute, or now with `refresh`) and what each
    cannot do.
    """
    providers: list[ProviderInfo] = []
    for engine in ctx.sessions.engines.all():
        info = ProviderInfo(
            name=engine.name,
            display_name=_DISPLAY_NAMES.get(engine.name, engine.name.capitalize()),
            signed_in=None,
            unsupported=sorted(engine.provider.unsupported),
        )
        if engine.name == CODEX:
            status = await ctx.codex.status(refresh=refresh)
            info.signed_in = status.signed_in
            info.account = status.account
            info.sign_in_hint = NOT_SIGNED_IN if status.signed_in is False else None
        else:
            info.account = await ctx.engine.account()
        providers.append(info)
    return ProviderList(providers=providers)
