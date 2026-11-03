import type { FoundModel } from "../../../api/types.ts";

// The Add local model sheet's choices (B106), as NestKit's AddLocalFlow.

export type AddTab = "find" | "address";

export const modelKey = (model: FoundModel) => `${model.address}/${model.model}`;

/**
 * `chosen` with the models a look found chosen: on Find those good at tools, on an
 * address any not weak at them. Added ones stay as they are, and a model too big for the
 * machine's memory is left to the user to choose.
 */
export function withFound(
  chosen: ReadonlySet<string>,
  models: readonly FoundModel[],
  tab: AddTab,
): Set<string> {
  const good = (m: FoundModel) =>
    m.tools === "good" || (tab === "address" && m.tools === "unknown");
  const next = new Set(chosen);
  for (const model of models) {
    if (!model.added && model.memory_warning === null && good(model)) next.add(modelKey(model));
  }
  return next;
}

/** Added models show chosen and cannot be unchosen. */
export function isChosen(chosen: ReadonlySet<string>, model: FoundModel): boolean {
  return model.added || chosen.has(modelKey(model));
}

/** The models Add sends: chosen and not added yet. */
export function picked(chosen: ReadonlySet<string>, choices: readonly FoundModel[]): FoundModel[] {
  return choices.filter((m) => !m.added && chosen.has(modelKey(m)));
}
