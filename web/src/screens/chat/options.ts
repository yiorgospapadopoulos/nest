import type { ModelOption, PermissionMode } from "../../api/types.ts";

export interface Option<T> {
  // Null leaves the choice to the agent defaults.
  value: T | null;
  label: string;
  hint?: string;
}

export type PickerKind = "model" | "effort" | "permission";

export const PICKER_TITLES: Record<PickerKind, string> = {
  model: "Model",
  effort: "Thinking",
  permission: "Permission mode",
};

// Shown in the composer while a new chat keeps the agent default.
export const DEFAULT_LABELS: Record<PickerKind, string> = {
  model: "Model",
  effort: "Thinking",
  permission: "Mode",
};

// The thinking selector's label when the model takes no thinking level (Haiku).
export const NO_THINKING = "Not available";

// The model a chat without a model uses: Claude Code's own default.
export const CLAUDE_DEFAULT = "default";

export const AGENT_DEFAULT: Option<string> = {
  value: null,
  label: "Default",
  hint: "Your agent default, set in Account",
};

const ALL_LEVELS = ["low", "medium", "high", "xhigh", "max"];

const EFFORT_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
};

export const PERMISSIONS: (Option<PermissionMode> & { value: PermissionMode })[] = [
  { value: "default", label: "Ask", hint: "Asks before edits and commands" },
  { value: "acceptEdits", label: "Accept edits", hint: "Edits files without asking" },
  { value: "plan", label: "Plan", hint: "Reads and plans only" },
  { value: "bypassPermissions", label: "Bypass", hint: "Runs everything without asking" },
];

/** Claude Code's models, in its order, with their descriptions. */
export function modelOptions(models: ModelOption[] | null): Option<string>[] {
  return (models ?? []).map((m) => ({
    value: m.value,
    label: m.display_name,
    hint: m.description,
  }));
}

/**
 * The thinking levels `model` takes (null is Claude Code's default); every level while the
 * model is not in the list, and none for a model without thinking.
 */
export function thinkingLevels(models: ModelOption[] | null, model: string | null): string[] {
  const found = models?.find((m) => m.value === (model ?? CLAUDE_DEFAULT));
  return found === undefined ? ALL_LEVELS : found.effort_levels;
}

/** A level's name; a level this app does not know yet shows as it is. */
export function effortLabel(level: string): string {
  return EFFORT_LABELS[level] ?? level;
}

export function effortOptions(levels: string[]): Option<string>[] {
  return levels.map((level) => ({ value: level, label: effortLabel(level) }));
}

/** The short label of a value; unknown models and levels show as they are. */
export function labelOf(
  kind: PickerKind,
  value: string | null,
  models: ModelOption[] | null,
): string {
  if (value === null) return DEFAULT_LABELS[kind];
  if (kind === "model") return models?.find((m) => m.value === value)?.display_name ?? value;
  if (kind === "effort") return effortLabel(value);
  return PERMISSIONS.find((o) => o.value === value)?.label ?? value;
}
