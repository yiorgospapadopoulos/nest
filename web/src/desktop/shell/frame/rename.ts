// The chat whose sidebar row is being renamed in place, as the Mac's shell.renaming: one at
// a time, started from the row's menu or from anywhere else that offers Rename.
import { useSyncExternalStore } from "react";

let renaming: string | null = null;
const listeners = new Set<() => void>();

function set(id: string | null) {
  renaming = id;
  for (const listener of [...listeners]) listener();
}

/** Turns the chat's sidebar row into its name field; the caller opens the sidebar. */
export function beginRename(id: string): void {
  set(id);
}

export function endRename(): void {
  set(null);
}

export function useRenaming(): string | null {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => renaming,
    () => null,
  );
}
