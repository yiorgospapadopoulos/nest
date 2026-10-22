import type { FeaturesCatalog } from "../../api/types.ts";

/**
 * The features showing "New" (B103): those the Mac calls new, plus those remembered as new
 * when the Features page first showed in this visit to Settings.
 */
export function newIds(
  catalog: FeaturesCatalog,
  remembered: readonly string[] | null,
): Set<string> {
  const ids = new Set(remembered);
  for (const f of catalog.groups.flatMap((g) => g.features)) if (f.new) ids.add(f.id);
  return ids;
}

/** How many of the catalog's features show "New". */
export function newCount(catalog: FeaturesCatalog, remembered: readonly string[] | null): number {
  const ids = newIds(catalog, remembered);
  return catalog.groups.flatMap((g) => g.features).filter((f) => ids.has(f.id)).length;
}
