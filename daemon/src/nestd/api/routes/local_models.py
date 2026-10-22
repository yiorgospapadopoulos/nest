"""Local models (B106): servers on this Mac or the network, added like accounts. A chat names
one as `local:<id>`. The translator the engines reach them through is not here: it is not
under device auth (`local_proxy`).
"""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from nestd.api.deps import Context, RequireDevice
from nestd.local.models import (
    AddModels,
    CheckResult,
    CheckServer,
    FoundModels,
    LocalModel,
    LocalModelList,
    LocalUsage,
    SetEngine,
    StartServer,
)

router = APIRouter(prefix="/api/local", dependencies=[RequireDevice])


class AddedModels(BaseModel):
    models: list[LocalModel]


@router.get("/models")
async def list_models(ctx: Context) -> LocalModelList:
    """Each model with whether its server answers now, the engine local chats run on and
    whether the user chose local models only.
    """
    return await ctx.local.listing()


@router.get("/find")
async def find_models(ctx: Context) -> FoundModels:
    """Servers running on this Mac's usual ports and the models downloaded on it."""
    return await ctx.local.find()


@router.post("/check")
async def check_server(body: CheckServer, ctx: Context) -> CheckResult:
    """What the server at `address` is and serves; 422 for an address that is none."""
    return await ctx.local.check(body.address, body.key)


@router.post("/models", status_code=status.HTTP_201_CREATED)
async def add_models(body: AddModels, ctx: Context) -> AddedModels:
    """Add the server and the chosen models; 409 `local_server_down` when it does not
    answer, 422 for a model it does not serve. A key goes to the Keychain.
    """
    return AddedModels(models=await ctx.local.add(body.address, body.key, body.models))


@router.delete("/models/{model_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_model(model_id: str, ctx: Context) -> Response:
    await ctx.local.remove(model_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/engine", status_code=status.HTTP_204_NO_CONTENT)
async def set_engine(body: SetEngine, ctx: Context) -> Response:
    """The engine new local chats run on."""
    await ctx.local.set_engine(body.engine)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/start", status_code=status.HTTP_202_ACCEPTED)
async def start_server(body: StartServer, ctx: Context) -> Response:
    """Start LM Studio's server or Ollama; 404 when it is not installed."""
    await ctx.local.start(body.app)
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.get("/usage")
async def local_usage(ctx: Context) -> LocalUsage:
    """Today's tokens on local models; never a cost."""
    return await ctx.local.usage()
