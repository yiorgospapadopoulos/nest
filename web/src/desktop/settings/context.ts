import { createContext, use } from "react";

/** What lasts for one visit to Settings, from its opening to its closing (B103). */
export interface SettingsVisit {
  // The features new when the Features page first showed in this visit, if it did.
  visitNew: string[] | null;
  setVisitNew: (ids: string[] | null) => void;
}

export const SettingsVisitContext = createContext<SettingsVisit | null>(null);

export function useSettingsVisit(): SettingsVisit {
  const visit = use(SettingsVisitContext);
  if (visit === null) throw new Error("useSettingsVisit outside Settings");
  return visit;
}
