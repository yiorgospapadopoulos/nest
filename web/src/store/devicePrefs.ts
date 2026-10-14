import type { Attachment } from "../api/types.ts";
import type { Draft } from "./state.ts";

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

// The teams folded in the pixie list (B40), by id.
export const FOLDED_TEAMS_KEY = "harness.foldedTeams";

export function loadFoldedTeams(storage: () => Storage): string[] {
  let saved: unknown;
  try {
    saved = JSON.parse(storage().getItem(FOLDED_TEAMS_KEY) ?? "[]");
  } catch {
    return [];
  }
  return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === "string") : [];
}

export function saveFoldedTeams(storage: () => Storage, ids: string[]): void {
  try {
    storage().setItem(FOLDED_TEAMS_KEY, JSON.stringify(ids));
  } catch {
    // Not remembered.
  }
}

// Unsent messages, per chat (see draftKey), so a reload or a closed app keeps them.
export const DRAFTS_KEY = "harness.drafts";

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
