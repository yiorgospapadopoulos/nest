import { createContext, useContext } from "react";
import type { Actions } from "./actions.ts";
import type { State } from "./state.ts";

export interface StoreValue {
  state: State;
  actions: Actions;
  // The daemon's address: the host this app was opened from (B105).
  address: string;
}

export const StoreContext = createContext<StoreValue | null>(null);

export function useStore(): StoreValue {
  const value = useContext(StoreContext);
  if (value === null) throw new Error("useStore needs a StoreProvider");
  return value;
}
