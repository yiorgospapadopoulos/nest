import { useSyncExternalStore } from "react";
import { keysText, shortcuts, type ShortcutAction } from "./shortcuts.ts";

/** A command's keys as the window shows them, drawn again when Settings changes them. */
export function useKeysText(): (action: ShortcutAction) => string {
  useSyncExternalStore(shortcuts.subscribe, () => shortcuts.version);
  return keysText;
}
