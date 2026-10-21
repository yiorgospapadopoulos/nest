import type { Attachment } from "../api/types.ts";
import type { Draft } from "./state.ts";

// Choices remembered on this device only. Storage can be unavailable (private browsing,
// blocked site data); the choice then lasts until the app is reloaded.

export const SHOW_AUTOMATED_KEY = "nest.showAutomatedChats";

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

// The teams folded in the pixie list (B40), by id.
export const FOLDED_TEAMS_KEY = "nest.foldedTeams";

export function loadFoldedTeams(storage: () => Storage): string[] {
  return loadNames(storage, FOLDED_TEAMS_KEY);
}

export function saveFoldedTeams(storage: () => Storage, ids: string[]): void {
  try {
    storage().setItem(FOLDED_TEAMS_KEY, JSON.stringify(ids));
  } catch {
    // Not remembered.
  }
}

// The engines the usage bar leaves out (B102), by name: the unchecked ones, so an engine
// added later starts shown.
export const USAGE_BAR_HIDDEN_KEY = "nest.usageBarHidden";

export function loadUsageBarHidden(storage: () => Storage): string[] {
  return loadNames(storage, USAGE_BAR_HIDDEN_KEY);
}

export function saveUsageBarHidden(storage: () => Storage, names: string[]): void {
  try {
    storage().setItem(USAGE_BAR_HIDDEN_KEY, JSON.stringify(names));
  } catch {
    // Not remembered.
  }
}

/** A saved list of names; anything malformed or unreadable is left out. */
function loadNames(storage: () => Storage, key: string): string[] {
  let saved: unknown;
  try {
    saved = JSON.parse(storage().getItem(key) ?? "[]");
  } catch {
    return [];
  }
  return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === "string") : [];
}

// Unsent messages, per chat (see draftKey), so a reload or a closed app keeps them.
export const DRAFTS_KEY = "nest.drafts";

function attachmentOf(value: unknown): Attachment[] {
  if (typeof value !== "object" || value === null) return [];
  const a = value as Record<string, unknown>;
  return typeof a.id === "string" && typeof a.filename === "string" ? [value as Attachment] : [];
}

/** The saved drafts; anything malformed or unreadable is left out. */
export function loadDrafts(storage: () => Storage): Record<string, Draft> {
  let saved: unknown;
  try {
    saved = JSON.parse(storage().getItem(DRAFTS_KEY) ?? "{}");
  } catch {
    return {};
  }
  if (typeof saved !== "object" || saved === null || Array.isArray(saved)) return {};
  const drafts: Record<string, Draft> = {};
  for (const [key, value] of Object.entries(saved as Record<string, unknown>)) {
    const draft = (typeof value === "object" && value !== null ? value : {}) as Partial<
      Record<keyof Draft, unknown>
    >;
    const text = typeof draft.text === "string" ? draft.text : "";
    const files = Array.isArray(draft.files) ? draft.files.flatMap(attachmentOf) : [];
    if (text !== "" || files.length > 0) drafts[key] = { text, files };
  }
  return drafts;
}

export function saveDrafts(storage: () => Storage, drafts: Record<string, Draft>): void {
  try {
    storage().setItem(DRAFTS_KEY, JSON.stringify(drafts));
  } catch {
    // Not saved; the drafts last until the app is closed.
  }
}
