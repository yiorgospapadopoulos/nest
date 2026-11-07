import { useStore } from "../../store/context.ts";
import { useUpdateRestart } from "../../store/updates.ts";
import { useBridge } from "../context.ts";

/**
 * Relaunch to update, opening the new app once (B130): when the update brings a new Nest,
 * the Tauri side starts a helper that waits for the daemon and opens the new app, and this
 * app quits, rather than loading again only to quit for the swap. A dev build stays and
 * waits for the daemon as before.
 */
export function useRelaunch() {
  const { state } = useStore();
  const bridge = useBridge();
  const app = state.updates.status?.app ?? null;
  return useUpdateRestart(
    "relaunch",
    app === null ? undefined : () => bridge.relaunchApp(app.version),
  );
}
