import type { CompactAtChoice, ModelOption, PermissionMode, PlanMode } from "../../api/types.ts";
import { tokens } from "../../format.ts";

export interface Option<T> {
  value: T;
  label: string;
  hint?: string;
}

export const PICKER_TITLES = {
  model: "Model",
  effort: "Thinking",
  permission: "Permission mode",
};

// The thinking selector's label when the model takes no thinking level (Haiku).
export const NO_THINKING = "Not available";

// The model a chat without a model uses: Claude Code's own default.
export const CLAUDE_DEFAULT = "default";

const EFFORT_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  xhigh: "Extra high",
  max: "Max",
};

const SHORT_LABELS: Record<string, string> = {
  Medium: "Med",
  "Extra high": "X-high",
  "Accept edits": "Edits",
};

/**
 * A selector's label in a narrow pane, as the Mac's PaneFit: a model without its version
 * ("Sonnet" for "Sonnet 5.5"), and "Med", "X-high", "Edits"; the label itself otherwise.
 */
export function shortChoiceLabel(kind: keyof typeof PICKER_TITLES, label: string): string {
  if (kind === "model") return label.split(" ")[0] ?? label;
  return SHORT_LABELS[label] ?? label;
}

// Every mode; "auto" only for the models that take it.
export const PERMISSIONS: Option<PermissionMode>[] = [
  { value: "default", label: "Ask", hint: "Asks before edits and commands" },
  { value: "acceptEdits", label: "Accept edits", hint: "Edits files without asking" },
  { value: "plan", label: "Plan", hint: "Reads and plans only" },
  { value: "bypassPermissions", label: "Bypass", hint: "Runs everything without asking" },
  { value: "auto", label: "Auto", hint: "Claude decides what needs asking" },
];

// How Claude goes on once a plan is approved; Auto only where the model takes it.
const PLAN_MODES: { value: PlanMode; label: string }[] = [
  { value: "acceptEdits", label: "Auto-accept edits" },
  { value: "default", label: "Approve edits manually" },
  { value: "auto", label: "Auto" },
];

/** Whether `model` (null is Claude Code's default) takes the "auto" permission mode. */
function takesAuto(models: ModelOption[] | null, model: string | null): boolean {
  return models?.find((m) => m.value === (model ?? CLAUDE_DEFAULT))?.supports_auto_mode === true;
}

/** The ways to go on after a plan that `model` takes. */
export function planModes(models: ModelOption[] | null, model: string | null) {
  const auto = takesAuto(models, model);
  return PLAN_MODES.filter((option) => auto || option.value !== "auto");
}

/** A level's name; a level this app does not know yet shows as it is. */
export function effortLabel(level: string): string {
  return EFFORT_LABELS[level] ?? level;
}

export function effortOptions(levels: string[]): Option<string>[] {
  return levels.map((level) => ({ value: level, label: effortLabel(level) }));
}

// The sizes a chat may compact at (B146); null is the engine's own.
const COMPACT_SIZES = [100_000, 300_000, 400_000, 700_000, 1_000_000];

export const COMPACT_AT_TITLE = "Compact at";

/** "Auto" for the engine's own, else the size, such as "300k" or "1M". */
export function compactAtLabel(size: number | null): string {
  return size === null ? "Auto" : tokens(size);
}

export const COMPACT_AT: Option<number | null>[] = [null, ...COMPACT_SIZES].map((size) => ({
  value: size,
  label: compactAtLabel(size),
}));

/** What a PATCH sends for a choice: "auto" for the engine's own. */
export function compactAtChoice(size: number | null): CompactAtChoice {
  return size ?? "auto";
}

/** A choice as a picker's or select's value, "auto" for the engine's own. */
export function compactAtPick(size: number | null): string {
  return String(compactAtChoice(size));
}

export function pickedCompactAt(value: string): number | null {
  return value === "auto" ? null : Number(value);
}

export const COMPACT_AT_PICKS: Option<string>[] = COMPACT_AT.map((option) => ({
  value: compactAtPick(option.value),
  label: option.label,
}));
