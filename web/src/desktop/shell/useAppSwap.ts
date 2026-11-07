import { useEffect, useRef } from "react";
import { useStore } from "../../store/context.ts";
import { useBridge } from "../context.ts";

/**
 * Once a launch, the app follows the daemon (B130): after an update or its undo the running
 * daemon names the app that belongs to it, and an app of another version swaps to that file.
 * The Tauri side keeps the same once-a-launch rule, as a reload starts this over.
 */
export function useAppSwap() {
  const { state } = useStore();
  const bridge = useBridge();
  const asked = useRef(false);
  const file = state.updates.status?.app_file ?? null;
  useEffect(() => {
    if (file === null || asked.current) return;
    asked.current = true;
    void (async () => {
      const own = await bridge.appVersion();
      if (own !== null && own !== file.version) await bridge.swapApp(file.path);
    })().catch(() => undefined);
  }, [bridge, file]);
}
