"""Skills and plugins in Settings (D104), through `claude plugin ...`. CLI failures are
502 with its message; every change is announced as `extensions.updated`."""

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, ConfigDict

from nestd.api.deps import Context, RequireDevice
from nestd.claude_code.extensions import (
    AvailablePlugin,
    InstalledPlugin,
    Marketplace,
    MarketplaceName,
    MarketplaceSource,
    PluginDetails,
    PluginId,
    Skill,
)

router = APIRouter(prefix="/api/extensions", dependencies=[RequireDevice])


class AddMarketplace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A URL, path or GitHub repo (`owner/name`).
    source: MarketplaceSource


class PluginEnabled(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


def _done() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/plugins")
async def installed_plugins(ctx: Context) -> list[InstalledPlugin]:
    return await ctx.extensions.plugins()


@router.get("/skills")
async def standalone_skills(ctx: Context) -> list[Skill]:
    """The user's own skills in `~/.claude/skills`, by name."""
    return await ctx.extensions.skills()


@router.get("/marketplaces")
async def marketplaces(ctx: Context) -> list[Marketplace]:
    return await ctx.extensions.marketplaces()


@router.post("/marketplaces", status_code=status.HTTP_204_NO_CONTENT)
async def add_marketplace(body: AddMarketplace, ctx: Context) -> Response:
    await ctx.extensions.add_marketplace(body.source)
    return _done()


@router.delete("/marketplaces/{name}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_marketplace(name: MarketplaceName, ctx: Context) -> Response:
    await ctx.extensions.remove_marketplace(name)
    return _done()


@router.get("/available")
async def available_plugins(ctx: Context) -> list[AvailablePlugin]:
    """Plugins of the configured marketplaces, installed ones included, by id."""
    return await ctx.extensions.available()


@router.get("/plugins/{plugin_id}/details")
async def plugin_details(plugin_id: PluginId, ctx: Context) -> PluginDetails:
    """`plugin_id` is `name@marketplace`; 404 when no marketplace has it."""
    return await ctx.extensions.details(plugin_id)


@router.post("/plugins/{plugin_id}/install", status_code=status.HTTP_204_NO_CONTENT)
async def install_plugin(plugin_id: PluginId, ctx: Context) -> Response:
    await ctx.extensions.install(plugin_id)
    return _done()


@router.post("/plugins/{plugin_id}/uninstall", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_plugin(plugin_id: PluginId, ctx: Context) -> Response:
    await ctx.extensions.uninstall(plugin_id)
    return _done()


@router.put("/plugins/{plugin_id}/enabled", status_code=status.HTTP_204_NO_CONTENT)
async def set_plugin_enabled(plugin_id: PluginId, body: PluginEnabled, ctx: Context) -> Response:
    await ctx.extensions.set_enabled(plugin_id, body.enabled)
    return _done()
