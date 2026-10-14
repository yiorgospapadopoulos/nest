import { STORAGE_KEY } from "../appearance/choices.ts";
import { DRAFTS_KEY, FOLDED_TEAMS_KEY, SHOW_AUTOMATED_KEY } from "./devicePrefs.ts";

// What this device saved before the rename to Nest (B43), by old and new key. Each is read
// once, saved under its new key and then removed.
export const LEGACY_KEYS: readonly (readonly [string, string])[] = [
  STORAGE_KEY,
  SHOW_AUTOMATED_KEY,
  FOLDED_TEAMS_KEY,
  DRAFTS_KEY,
].map((key) => [key.replace(/^nest\./, "harness."), key] as const);

export function migrateLegacyKeys(storage: Storage): void {
  for (const [old, key] of LEGACY_KEYS) {
    try {
      const saved = storage.getItem(old);
      if (saved === null) continue;
      if (storage.getItem(key) === null) storage.setItem(key, saved);
      storage.removeItem(old);
    } catch {
      // Not moved; the old value stays for the next start.
    }
  }
}

const migrated = new WeakSet<Storage>();

/** This device's storage, with the keys from before the rename moved on first use. */
export function deviceStorage(): Storage {
  const storage = window.localStorage;
  if (!migrated.has(storage)) {
    migrated.add(storage);
    migrateLegacyKeys(storage);
  }
  return storage;
}
