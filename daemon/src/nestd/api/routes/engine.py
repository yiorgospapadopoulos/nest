"""The engines' models and accounts, for clients' pickers and profile (D038, B91, B107)."""

from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel

from nestd.api.deps import Context, RequireDevice
from nestd.engine.acp import AcpEngineService
from nestd.engine.acp_install import EngineNotInstallableError, EngineState
from nestd.engine.models import ModelList
from nestd.errors import NotFoundError
from nestd.providers.acp_engines import ACP_ENGINES, AcpEngine
from nestd.providers.base import AccountInfo, ProviderFeature
from nestd.providers.codex_engine import NOT_SIGNED_IN
from nestd.sessions.engines import Engine

router = APIRouter(prefix="/api", dependencies=[RequireDevice])

type ProviderName = Literal["claude", "codex", "opencode", "gemini", "cursor"]
type SignInKind = Literal["browser", "api_key", "terminal"]
CODEX = "codex"
_DISPLAY_NAMES = {
    "claude": "Claude",
    "codex": "Codex",
    **{engine.id: engine.name for engine in ACP_ENGINES},
}


class ProviderInfo(BaseModel):
    """An engine a new chat can run on (B91, B107)."""

    # What a new chat's `provider` is set to.
    name: str
    display_name: str
    # Whether it can run chats now; None when Nest does not check (Claude) or the engine
    # could not be asked. Codex stays offered when false: its chats fail with
    # `codex_not_signed_in` until the user signs in.
    signed_in: bool | None
    # What to tell the user when `signed_in` is false.
    sign_in_hint: str | None = None
    account: AccountInfo | None = None
    # What its chats cannot do, which clients hide; refused with `unsupported_feature`.
    unsupported: list[ProviderFeature]
    # The installed engine's version (B107); None for Claude and Codex, or when not known.
    version: str | None = None
    # False: Nest has not tried it live, shown as "untested".
    tested: bool = True
    # False: Nest cannot block its git commands, so Settings warns and pixies refuse it.
    git_guard: bool = True
    # Only a `ready` engine that is not signed out is offered for new chats.
    state: EngineState = "ready"
    # Why it is not installed, or why installing it failed, in plain words.
    state_detail: str | None = None
    sign_in: SignInKind = "browser"
    # The command the user runs in Terminal to sign in, for `sign_in` "terminal".
    login_command: str | None = None
    # Nest can fetch it itself (B107); False for Claude and Codex, which come with Nest, and
    # for an engine the user installs (Cursor).
    installable: bool = False


class ProviderList(BaseModel):
    """`GET /api/providers`: the default engine first, the ACP engines in Nest's order."""

    providers: list[ProviderInfo]


@router.get("/models")
async def list_models(ctx: Context, provider: ProviderName = "claude") -> ModelList:
    """The engine's model list in its order: Claude Code's (its aliases until it reported
    one), or another engine's (empty until it could be asked).
    """
    if provider == CODEX:
        return await ctx.codex.models()
    service = ctx.acp.get(provider)
    if service is not None:
        return await service.models()
    return await ctx.engine.models()


@router.get("/account")
async def account(ctx: Context, provider: ProviderName = "claude") -> AccountInfo:
    """Who the engine is signed in as; all null until it reported it, and always for the
    ACP engines, which do not say.
    """
    if provider == CODEX:
        return await ctx.codex.account()
    if provider in ctx.acp:
        return AccountInfo()
    return await ctx.engine.account()


@router.get("/providers")
async def list_providers(ctx: Context, refresh: bool = False) -> ProviderList:
    """The engines chats can run on, with Claude's account as its engine last reported it,
    Codex's login and each ACP engine's install and sign in (asked at most once a minute,
    or now with `refresh`) and what each cannot do.
    """
    providers = [await _info(ctx, engine, refresh) for engine in ctx.sessions.engines.all()]
    return ProviderList(providers=providers)


@router.post("/engines/{name}/install", status_code=status.HTTP_202_ACCEPTED)
async def install_engine(name: str, ctx: Context) -> ProviderInfo:
    """Start installing a pinned engine in the background (B107); its progress comes as
    `engine.state`. 404 for an engine Nest does not run, 409 for one the user installs.
    """
    service = _service(ctx, name)
    if not service.install.fetched:
        msg = f"Nest does not install {service.engine.name}: install it yourself"
        raise EngineNotInstallableError(msg)
    service.install.start()
    service.forget()
    return await _info(ctx, ctx.sessions.engines.named(name), refresh=False)


def _service(ctx: Context, name: str) -> AcpEngineService:
    service = ctx.acp.get(name)
    if service is None:
        msg = f"no engine {name!r} to install"
        raise NotFoundError(msg)
    return service


async def _info(ctx: Context, engine: Engine, refresh: bool) -> ProviderInfo:
    info = ProviderInfo(
        name=engine.name,
        display_name=_DISPLAY_NAMES.get(engine.name, engine.name.capitalize()),
        signed_in=None,
        unsupported=sorted(engine.unsupported),
    )
    service = ctx.acp.get(engine.name)
    if engine.name == CODEX:
        codex = await ctx.codex.status(refresh=refresh)
        info.signed_in = codex.signed_in
        info.account = codex.account
        info.sign_in_hint = NOT_SIGNED_IN if codex.signed_in is False else None
    elif service is not None:
        acp = await service.status(refresh=refresh)
        info.signed_in = acp.signed_in
        info.version = acp.version
        info.tested = service.engine.tested
        info.git_guard = service.engine.git_guard
        info.state = acp.state
        info.state_detail = acp.state_detail
        info.sign_in = service.engine.sign_in
        info.login_command = acp.login_command
        info.installable = service.install.fetched
        info.sign_in_hint = _hint(service.engine) if acp.signed_in is False else None
    else:
        info.account = await ctx.engine.account()
    return info


def _hint(engine: AcpEngine) -> str:
    if engine.sign_in == "api_key":
        return f"Add your {engine.name} API key in Settings > Accounts."
    return f"Sign in to {engine.name} with `{engine.login_command}` in Terminal."
