import type { AgentDefaults, Effort, ModelOption, PermissionMode } from "../api/types.ts";

// One engine's models and what its menus offer from them, as NestKit's ModelCatalog and
// NewChatChoices (B91, B94): real models only, the engine's default model named, so a chat
// or pixie without a model reads as that one.

export const CLAUDE = "claude";

// The value both engines' lists use for the entry that defers to the engine (B94).
const ENGINE_DEFAULT = "default";

const LEVELS: Effort[] = ["low", "medium", "high", "xhigh", "max"];
const MEDIUM = LEVELS.indexOf("medium");

export interface ModelCatalog {
  // Empty until loaded.
  models: ModelOption[];
  // The model the engine runs when none is named; null while unknown.
  defaultModel: string | null;
}

/** The list without the engine's default entry, which is never offered (B94). */
export function realModels(models: ModelOption[]): ModelOption[] {
  return models.filter((m) => m.value !== ENGINE_DEFAULT);
}

// A bare family name, such as "opus", which Claude Code resolves to its newest model.
const ALIAS = /^[a-z]+$/;

/**
 * The list entry for a model; none (a chat from before B94) is the engine's default. A
 * model id or a family alias a chat holds reads as the listed model it stands for: the one
 * resolving to it, or the family's first, as the list puts the newest first (B102).
 */
export function modelInfo(catalog: ModelCatalog, model: string | null): ModelOption | undefined {
  const value = model ?? catalog.defaultModel;
  if (value === null) return undefined;
  const id = (m: ModelOption) => m.resolved_model ?? m.value;
  const alias = value.toLowerCase();
  return (
    catalog.models.find((m) => m.value === value) ??
    catalog.models.find((m) => m.resolved_model === value) ??
    (ALIAS.test(alias) ? catalog.models.find((m) => id(m).includes(alias)) : undefined)
  );
}

/** The model's display name, or its raw value when the list does not have it. */
export function modelLabel(catalog: ModelCatalog, model: string | null): string {
  return modelInfo(catalog, model)?.display_name ?? model ?? catalog.defaultModel ?? "Model";
}

export function isSelected(catalog: ModelCatalog, option: ModelOption, model: string | null) {
  return modelInfo(catalog, model) === option;
}

/** The model's own thinking levels in order, or every level for a model the list lacks. */
export function thinkingLevels(catalog: ModelCatalog, model: string | null): Effort[] {
  const info = modelInfo(catalog, model);
  if (info === undefined) return LEVELS;
  return info.supports_effort ? LEVELS.filter((l) => info.effort_levels.includes(l)) : [];
}

/** Medium, or the level nearest it (the lower of two as near); null without levels. */
export function standardEffort(levels: Effort[]): Effort | null {
  const offered = LEVELS.filter((l) => levels.includes(l));
  const distance = (l: Effort) => Math.abs(LEVELS.indexOf(l) - MEDIUM);
  return offered.reduce<Effort | null>(
    (best, l) => (best === null || distance(l) < distance(best) ? l : best),
    null,
  );
}

/** The current level, or the highest level below it that the model takes. */
export function fallbackEffort(current: Effort | null, levels: Effort[]): Effort | null {
  if (current === null) return null;
  return LEVELS.slice(0, LEVELS.indexOf(current) + 1).findLast((l) => levels.includes(l)) ?? null;
}

/** The thinking a chat keeps after switching to `model`, else Medium or the nearest. */
export function effortAfterSwitching(
  catalog: ModelCatalog,
  current: Effort | null,
  model: string | null,
): Effort | null {
  const levels = thinkingLevels(catalog, model);
  return fallbackEffort(current, levels) ?? standardEffort(levels);
}

/** The model offers the Auto mode; unknown models do not. */
export function supportsAuto(catalog: ModelCatalog, model: string | null): boolean {
  return modelInfo(catalog, model)?.supports_auto_mode === true;
}

/**
 * The mode a new chat keeps after switching to `model`: Auto only where the model offers
 * it, else `fallback` (the agent default) when it names another mode, else Ask.
 */
export function newChatPermission(
  catalog: ModelCatalog,
  current: PermissionMode | null,
  model: string | null,
  fallback: PermissionMode,
): PermissionMode {
  const mode = current ?? fallback;
  if (mode !== "auto" || supportsAuto(catalog, model)) return mode;
  return fallback === "auto" ? "default" : fallback;
}

/** A new chat's engine, model, thinking and mode, sent with its first message. */
export interface NewChatChoices {
  provider: string;
  model: string | null;
  effort: Effort | null;
  permission: PermissionMode;
}

const engineOf = (defaults: AgentDefaults) => defaults.provider ?? CLAUDE;
const modeOf = (defaults: AgentDefaults) => defaults.permission_mode ?? "default";

/** The new chat's choices from the agent defaults; `catalog` is their engine's. */
export function newChatChoices(defaults: AgentDefaults, catalog: ModelCatalog): NewChatChoices {
  const model = defaults.model ?? catalog.defaultModel;
  return {
    provider: engineOf(defaults),
    model,
    effort: defaults.effort ?? standardEffort(thinkingLevels(catalog, model)),
    permission: newChatPermission(catalog, null, model, modeOf(defaults)),
  };
}

/**
 * The choices on another engine, whose `catalog` is given: the defaults' engine takes
 * their model and thinking again; any other starts on its own default model with Medium
 * or the nearest level. The mode stays where the new model allows it.
 */
export function switchingEngine(
  choices: NewChatChoices,
  provider: string,
  catalog: ModelCatalog,
  defaults: AgentDefaults,
): NewChatChoices {
  if (provider === choices.provider) return choices;
  const own = provider === engineOf(defaults);
  const model = own ? (defaults.model ?? catalog.defaultModel) : catalog.defaultModel;
  return {
    provider,
    model,
    effort: effortAfterSwitching(catalog, own ? defaults.effort : null, model),
    permission: newChatPermission(catalog, choices.permission, model, modeOf(defaults)),
  };
}

/** A model chosen from `provider`'s section: the engine follows, then thinking and mode. */
export function choosingModel(
  choices: NewChatChoices,
  model: string,
  provider: string,
  catalog: ModelCatalog,
  defaults: AgentDefaults,
): NewChatChoices {
  const next = switchingEngine(choices, provider, catalog, defaults);
  return {
    provider,
    model,
    effort: effortAfterSwitching(catalog, next.effort, model),
    permission: newChatPermission(catalog, next.permission, model, modeOf(defaults)),
  };
}
