import type { AvailablePlugin, PluginDetails } from "../../../api/types.ts";

// Browse's words and search, as NestKit's Extensions.swift.

/** The plugins whose name, marketplace, id or description hold every typed word. */
export function matching(plugins: readonly AvailablePlugin[], query: string): AvailablePlugin[] {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (words.length === 0) return [...plugins];
  return plugins.filter((plugin) => {
    const text = [plugin.name, plugin.marketplace, plugin.id, plugin.description ?? ""]
      .join(" ")
      .toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

type Components = NonNullable<PluginDetails["components"]>;

const PARTS: [keyof Components, string, string][] = [
  ["skills", "skill", "skills"],
  ["agents", "agent", "agents"],
  ["hooks", "hook", "hooks"],
  ["mcp_servers", "MCP server", "MCP servers"],
  ["lsp_servers", "LSP server", "LSP servers"],
];

/** "2 skills, 1 MCP server": what a plugin brings, parts it has none of left out. */
export function componentSummary(components: Components): string[] {
  return PARTS.flatMap(([key, one, many]) => {
    const count = components[key].count;
    if (count === 0) return [];
    return [count === 1 ? `1 ${one}` : `${String(count)} ${many}`];
  });
}

/** The skills', agents' and MCP servers' names, one line each where there are any. */
export function componentNames(components: Components): string[] {
  return [components.skills, components.agents, components.mcp_servers]
    .filter((part) => part.names.length > 0)
    .map((part) => part.names.join(", "));
}
