// Choices remembered on this device only. Storage can be unavailable (private browsing,
// blocked site data); the choice then lasts until the app is reloaded.

export const SHOW_AUTOMATED_KEY = "harness.showAutomatedChats";

export function loadShowAutomated(storage: () => Storage): boolean {
  try {
    return storage().getItem(SHOW_AUTOMATED_KEY) === "true";
  } catch {
    return false;
  }
}

export function saveShowAutomated(storage: () => Storage, on: boolean): void {
  try {
    storage().setItem(SHOW_AUTOMATED_KEY, String(on));
  } catch {
    // Not remembered.
  }
}
