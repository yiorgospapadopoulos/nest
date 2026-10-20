"""Codex's own plugins and marketplaces in Codex's section (B97), through its app-server.

Browsing filters `plugin/list` in Nest (`plugin/search` is not on the stable API).
"""

from pydantic import BaseModel

from nestd.configuration.codex import (
    CodexCatalog,
    CodexMarketplace,
    CodexPlugin,
    CodexSetup,
    read_catalog,
)
from nestd.configuration.errors import UnknownItemError
from nestd.providers.codex_rpc import CodexRpc


class CodexPlugins(BaseModel):
    plugins: list[CodexPlugin]
    marketplaces: list[CodexMarketplace]


class CodexPluginSetup:
    def __init__(self, codex: CodexSetup) -> None:
        self._codex = codex

    async def plugins(self, query: str = "") -> CodexPlugins:
        """Installed ones first, then by name; `query` matches the id, name or description."""
        catalog = await self._codex.ask(read_catalog)
        return _listing(catalog, query)

    async def install(self, plugin_id: str) -> CodexPlugins:
        """404 when no marketplace Codex knows has it."""

        async def install(rpc: CodexRpc) -> CodexCatalog:
            catalog = await read_catalog(rpc)
            plugin = next((p for p in catalog.plugins if p.id == plugin_id), None)
            if plugin is None:
                raise UnknownItemError(f"no Codex plugin {plugin_id!r}")
            await rpc.request(
                "plugin/install",
                {
                    "pluginName": plugin.name,
                    "marketplacePath": catalog.marketplace_paths[plugin.id],
                },
            )
            return await read_catalog(rpc)

        return _listing(await self._codex.ask(install), "")

    async def uninstall(self, plugin_id: str) -> CodexPlugins:
        async def uninstall(rpc: CodexRpc) -> CodexCatalog:
            await rpc.request("plugin/uninstall", {"pluginId": plugin_id})
            return await read_catalog(rpc)

        return _listing(await self._codex.ask(uninstall), "")

    async def marketplaces(self) -> list[CodexMarketplace]:
        return (await self._codex.ask(read_catalog)).marketplaces

    async def add_marketplace(self, source: str) -> list[CodexMarketplace]:
        async def add(rpc: CodexRpc) -> CodexCatalog:
            await rpc.request("marketplace/add", {"source": source})
            return await read_catalog(rpc)

        return (await self._codex.ask(add)).marketplaces

    async def remove_marketplace(self, name: str) -> list[CodexMarketplace]:
        async def remove(rpc: CodexRpc) -> CodexCatalog:
            await rpc.request("marketplace/remove", {"marketplaceName": name})
            return await read_catalog(rpc)

        return (await self._codex.ask(remove)).marketplaces


def _listing(catalog: CodexCatalog, query: str) -> CodexPlugins:
    words = query.casefold().split()

    def matches(plugin: CodexPlugin) -> bool:
        text = f"{plugin.id} {plugin.name} {plugin.description or ''}".casefold()
        return all(word in text for word in words)

    plugins = sorted(
        (plugin for plugin in catalog.plugins if matches(plugin)),
        key=lambda plugin: (not plugin.installed, plugin.name, plugin.id),
    )
    return CodexPlugins(plugins=plugins, marketplaces=catalog.marketplaces)
