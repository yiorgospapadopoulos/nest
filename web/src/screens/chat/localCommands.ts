import type { ModelOption, SlashCommand } from "../../api/types.ts";

/**
 * Claude Code's interactive commands, which the SDK cannot run: Nest opens its own screen
 * for each instead of sending it to Claude (B59).
 */
export interface LocalCommand {
  name: "model" | "permissions" | "mcp" | "resume";
  arg: string;
}

export const LOCAL_COMMANDS: SlashCommand[] = [
  { name: "mcp", description: "Show MCP servers and connectors", argument_hint: null },
  { name: "model", description: "Set the model for this chat", argument_hint: "[model]" },
  { name: "permissions", description: "Choose the permission mode", argument_hint: null },
  { name: "resume", description: "Resume another chat", argument_hint: "[search]" },
];

const PATTERN = /^\/(model|permissions|mcp|resume)(?:\s+([\s\S]*))?$/;

/** The message as one of Nest's own commands, with what follows it; null for any other. */
export function localCommand(text: string): LocalCommand | null {
  const match = PATTERN.exec(text.trim());
  if (match === null) return null;
  return { name: match[1] as LocalCommand["name"], arg: (match[2] ?? "").trim() };
}

/** The chat's commands with Nest's own ones in place of any of the same name, by name. */
export function withLocalCommands(commands: SlashCommand[]): SlashCommand[] {
  const local = new Set(LOCAL_COMMANDS.map((c) => c.name));
  return [...LOCAL_COMMANDS, ...commands.filter((c) => !local.has(c.name))].sort((a, b) =>
    a.name.localeCompare(b.name),
  );
}

/** The listed model `/model <name>` names, by its id or its name (any case). */
export function namedModel(models: ModelOption[], name: string): string | null {
  const wanted = name.toLowerCase();
  const found = models.find(
    (m) => m.value.toLowerCase() === wanted || m.display_name.toLowerCase() === wanted,
  );
  return found?.value ?? null;
}
