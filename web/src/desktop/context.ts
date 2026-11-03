import { createContext, use } from "react";
import type { Api } from "../api/client.ts";
import { browserBridge, type Bridge } from "./bridge.ts";

export const BridgeContext = createContext<Bridge>(browserBridge({ search: "" }, null));

export function useBridge(): Bridge {
  return use(BridgeContext);
}

// The daemon's API, for the desktop's own calls the shared store has no action for.
export const ApiContext = createContext<Api | null>(null);

export function useApi(): Api {
  const api = use(ApiContext);
  if (api === null) throw new Error("useApi outside the desktop app");
  return api;
}
