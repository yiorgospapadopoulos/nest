"""Settings > Configuration (B97): what the engines share and each engine's own setup,
read and written in the engines' own files. 403 for a path outside the allow-list, 404
for an unknown item, 409 for a conflict (with `current_version` for a file), 422 for
invalid input. Changes on disk come as `configuration.changed`.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, StringConstraints

from nestd.api.deps import Context, RequireDevice
from nestd.configuration import copying
from nestd.configuration.codex import CodexMarketplace
from nestd.configuration.mcp import NAME_PATTERN, McpServer
from nestd.configuration.models import (
    ConfigurationPage,
    CopyPreview,
    CopyResult,
    EngineId,
    FileText,
    FileVersion,
    ProjectConfiguration,
    SharedItem,
)
from nestd.configuration.plugins import CodexPlugins

router = APIRouter(prefix="/api", dependencies=[RequireDevice])

type ServerName = Annotated[str, StringConstraints(pattern=NAME_PATTERN)]
type SkillName = Annotated[str, StringConstraints(min_length=1, max_length=64)]
type Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1024)]
_ID = r"^[A-Za-z0-9][A-Za-z0-9._@:-]*$"
type CodexPluginId = Annotated[str, StringConstraints(pattern=_ID, max_length=200)]
type MarketplaceName = Annotated[str, StringConstraints(pattern=_ID, max_length=200)]
# A URL, path or GitHub repo; never something read as an option.
type MarketplaceSource = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, pattern=r"^[^-\s]")
]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WriteFile(_Body):
    path: str
    text: str
    # The version the client read; null when it saw no file.
    expected_version: str | None


class UsesSharedChange(_Body):
    engine: EngineId
    item: SharedItem
    on: bool


class NewSkill(_Body):
    name: SkillName
    description: Description = ""


class MakeShared(_Body):
    # Only Codex has skills of its own outside the shared folder.
    engine: Literal["codex"] = "codex"


class SkillEnabled(_Body):
    enabled: bool


class CopyRequest(_Body):
    # False keeps the shared instructions as they are.
    instructions: bool


class NewMarketplace(_Body):
    source: MarketplaceSource


@router.get("/configuration")
async def configuration_page(ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.page()


@router.get("/configuration/file")
async def read_file(path: Annotated[str, Query()], ctx: Context) -> FileText:
    """A missing file has text "" and version null."""
    return await ctx.configuration.read_file(path)


@router.put("/configuration/file")
async def write_file(body: WriteFile, ctx: Context) -> FileVersion:
    return await ctx.configuration.write_file(body.path, body.text, body.expected_version)


@router.put("/configuration/uses-shared")
async def set_uses_shared(body: UsesSharedChange, ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.set_uses_shared(body.engine, body.item, body.on)


@router.post("/configuration/skills")
async def create_skill(body: NewSkill, ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.create_skill(body.name, body.description)


@router.delete("/configuration/skills/{name}")
async def delete_skill(name: SkillName, ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.delete_skill(name)


@router.post("/configuration/skills/{name}/make-shared")
async def make_shared(name: SkillName, body: MakeShared, ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.make_shared(name)


@router.put("/configuration/skills/{name}/engines/codex")
async def set_codex_skill(name: SkillName, body: SkillEnabled, ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.set_codex_skill(name, body.enabled)


@router.get("/configuration/mcp-servers/{name}")
async def mcp_server(name: ServerName, ctx: Context) -> McpServer:
    """The server in Claude's shape, for the edit form."""
    return await ctx.configuration.server(name)


@router.put("/configuration/mcp-servers/{name}")
async def put_mcp_server(name: ServerName, body: McpServer, ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.put_server(name, body)


@router.delete("/configuration/mcp-servers/{name}")
async def delete_mcp_server(name: ServerName, ctx: Context) -> ConfigurationPage:
    return await ctx.configuration.delete_server(name)


@router.get("/configuration/copy/{engine}")
async def copy_preview(engine: EngineId, ctx: Context) -> CopyPreview:
    return await copying.preview(ctx.configuration, engine)


@router.post("/configuration/copy/undo/{undo_id}")
async def undo_copy(undo_id: str, ctx: Context) -> ConfigurationPage:
    return await copying.undo(ctx.configuration, undo_id)


@router.post("/configuration/copy/{engine}")
async def copy_to_shared(engine: EngineId, body: CopyRequest, ctx: Context) -> CopyResult:
    return await copying.copy(ctx.configuration, engine, body.instructions)


@router.get("/configuration/codex/plugins")
async def codex_plugins(ctx: Context, query: str = "") -> CodexPlugins:
    """Every plugin of Codex's marketplaces, installed first; `query` filters them."""
    return await ctx.codex_plugins.plugins(query)


@router.post("/configuration/codex/plugins/{plugin_id}/install")
async def install_codex_plugin(plugin_id: CodexPluginId, ctx: Context) -> CodexPlugins:
    return await ctx.codex_plugins.install(plugin_id)


@router.post("/configuration/codex/plugins/{plugin_id}/uninstall")
async def uninstall_codex_plugin(plugin_id: CodexPluginId, ctx: Context) -> CodexPlugins:
    return await ctx.codex_plugins.uninstall(plugin_id)


@router.get("/configuration/codex/marketplaces")
async def codex_marketplaces(ctx: Context) -> list[CodexMarketplace]:
    return await ctx.codex_plugins.marketplaces()


@router.post("/configuration/codex/marketplaces")
async def add_codex_marketplace(body: NewMarketplace, ctx: Context) -> list[CodexMarketplace]:
    return await ctx.codex_plugins.add_marketplace(body.source)


@router.delete("/configuration/codex/marketplaces/{name}")
async def remove_codex_marketplace(name: MarketplaceName, ctx: Context) -> list[CodexMarketplace]:
    return await ctx.codex_plugins.remove_marketplace(name)


@router.get("/repos/{name}/configuration")
async def project_configuration(name: str, ctx: Context) -> ProjectConfiguration:
    return await ctx.project_setup.read(ctx.repos.get(name).path)


@router.put("/repos/{name}/configuration/mcp-servers/{server}")
async def put_project_server(
    name: str, server: ServerName, body: McpServer, ctx: Context
) -> ProjectConfiguration:
    return await ctx.project_setup.put_server(ctx.repos.get(name).path, server, body)


@router.delete("/repos/{name}/configuration/mcp-servers/{server}")
async def delete_project_server(
    name: str, server: ServerName, ctx: Context
) -> ProjectConfiguration:
    return await ctx.project_setup.delete_server(ctx.repos.get(name).path, server)


@router.post("/repos/{name}/configuration/skills")
async def create_project_skill(name: str, body: NewSkill, ctx: Context) -> ProjectConfiguration:
    return await ctx.project_setup.create_skill(
        ctx.repos.get(name).path, body.name, body.description
    )
