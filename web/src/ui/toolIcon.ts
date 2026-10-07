import type { IconName } from "./Icon.tsx";

// The icon a tool call shows in the transcript and the Agents sheet.
const TOOL_ICONS: Record<string, IconName> = {
  Read: "file",
  Edit: "edit",
  Write: "edit",
  MultiEdit: "edit",
  Bash: "term",
  Grep: "search",
  Glob: "search",
  Task: "bot",
  Agent: "bot",
};

export function toolIcon(tool: string): IconName {
  return TOOL_ICONS[tool] ?? "term";
}
