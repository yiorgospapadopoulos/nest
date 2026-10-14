import type { ModelOption, PermissionMode, PlanMode } from "../../api/types.ts";

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

type PermissionOption = Option<PermissionMode> & { value: PermissionMode };

// Every mode; "auto" only for the models that take it (see permissionOptions).
export const PERMISSIONS: PermissionOption[] = [
  { value: "default", label: "Ask", hint: "Asks before edits and commands" },
  { value: "acceptEdits", label: "Accept edits", hint: "Edits files without asking" },
  { value: "plan", label: "Plan", hint: "Reads and plans only" },
  { value: "bypassPermissions", label: "Bypass", hint: "Runs everything without asking" },
  { value: "auto", label: "Auto", hint: "Claude decides what needs asking" },
];

// The agent default that leaves the mode to Claude Code's own settings.
export const CLAUDE_CODE_MODE = "Claude Code default";

// How Claude goes on once a plan is approved; Auto only where the model takes it.
export const PLAN_MODES: { value: PlanMode; label: string }[] = [
  { value: "acceptEdits", label: "Auto-accept edits" },
  { value: "default", label: "Approve edits manually" },
  { value: "auto", label: "Auto" },
];

/** The listed model `model` runs (null is Claude Code's default), if it is listed. */
export function findModel(
  models: ModelOption[] | null,
  model: string | null,
): ModelOption | undefined {
  return models?.find((m) => m.value === (model ?? CLAUDE_DEFAULT));
}

/** Whether `model` takes the "auto" permission mode; unknown models do not. */
export function takesAuto(models: ModelOption[] | null, model: string | null): boolean {
  return findModel(models, model)?.supports_auto_mode === true;
}

/** The permission modes `model` takes. */
export function permissionOptions(
  models: ModelOption[] | null,
  model: string | null,
): PermissionOption[] {
  const auto = takesAuto(models, model);
  return PERMISSIONS.filter((option) => auto || option.value !== "auto");
}

/** The ways to go on after a plan that `model` takes. */
export function planModes(models: ModelOption[] | null, model: string | null) {
  const auto = takesAuto(models, model);
  return PLAN_MODES.filter((option) => auto || option.value !== "auto");
}

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
  const found = findModel(models, model);
  return found === undefined ? ALL_LEVELS : found.effort_levels;
}

/**
 * The thinking default's name: "Model default", with the level Claude Code's settings
 * give the model when they set one.
 */
export function modelDefaultEffort(models: ModelOption[] | null, model: string | null): string {
  const level = findModel(models, model)?.claude_code_effort ?? null;
  return level === null
    ? "Model default"
    : `Model default (${effortLabel(level)}, from Claude Code)`;
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
