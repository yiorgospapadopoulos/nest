import { useCallback } from "react";
import { useStore } from "../../../store/context.ts";
import { useBridge } from "../../context.ts";

/**
 * Runs a settings change; a failure shows as "Could not ...: why", as the Mac's
 * settingsChange does.
 */
export function useSettingsChange() {
  const { actions } = useStore();
  return useCallback(
    (failure: string, work: () => Promise<unknown>) => {
      work().catch((error: unknown) => {
        const why = error instanceof Error ? error.message : String(error);
        actions.toast(`${failure}: ${why}`, "error");
      });
    },
    [actions],
  );
}

/**
 * Opens a folder in the file manager, or with `reveal` shows a file in its folder, as the
 * Mac's LocalOpen; null outside the desktop app, where these buttons do not show. With
 * `create`, a folder not there yet, such as the skills folder on a new machine, is made first.
 */
export function useOpenPath(): ((path: string, reveal?: boolean, create?: boolean) => void) | null {
  const bridge = useBridge();
  const change = useSettingsChange();
  if (!bridge.native) return null;
  return (path, reveal = false, create = false) => {
    change(reveal ? "Could not show the file" : "Could not open the folder", () =>
      create ? bridge.openPath(path, reveal, true) : bridge.openPath(path, reveal),
    );
  };
}

/** A path under a home folder with `~` for it. */
export function shortPath(path: string): string {
  return path.replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, "~");
}

export function fileName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}
