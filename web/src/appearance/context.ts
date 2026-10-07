import { createContext, useContext } from "react";
import { DEFAULT_APPEARANCE, type Appearance } from "./appearance.ts";

export interface AppearanceValue {
  appearance: Appearance;
  change: (patch: Partial<Appearance>) => void;
}

export const AppearanceContext = createContext<AppearanceValue>({
  appearance: DEFAULT_APPEARANCE,
  change: () => undefined,
});

export function useAppearance(): AppearanceValue {
  return useContext(AppearanceContext);
}
