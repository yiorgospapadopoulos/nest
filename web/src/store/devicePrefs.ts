import type { Attachment, IssueShow } from "../api/types.ts";
import type { Draft } from "./state.ts";
import type { UsageMeterChoice } from "./usageMeter.ts";

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

// The name of the machine whose daemon serves this app (B105), so the notice shown while it
// cannot be reached can name it.
export const MACHINE_KEY = "nest.machine";

export function loadMachine(storage: () => Storage): string | null {
  try {
    return storage().getItem(MACHINE_KEY);
  } catch {
    return null;
  }
}

export function saveMachine(storage: () => Storage, machine: string): void {
  try {
    storage().setItem(MACHINE_KEY, machine);
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

// The accounts "Top bar shows" checks, in their order (B98): `{order, shown}`, `shown` null
// until the user checks or unchecks one. Until then the engines unchecked in
// `nest.usageBarHidden` start unchecked; the first check replaces that key.
export const USAGE_METER_KEY = "nest.usageMeter";

const ids = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((id): id is string => typeof id === "string") : [];

export function loadUsageMeter(storage: () => Storage): UsageMeterChoice {
  let saved: unknown;
  try {
    saved = JSON.parse(storage().getItem(USAGE_METER_KEY) ?? "{}");
  } catch {
    saved = {};
  }
  const choice = (typeof saved === "object" && saved !== null ? saved : {}) as Record<
    string,
    unknown
  >;
  const shown = Array.isArray(choice.shown) ? ids(choice.shown) : null;
  return {
    order: ids(choice.order),
    shown,
    hiddenEngines: shown === null ? loadUsageBarHidden(storage) : [],
  };
}

export function saveUsageMeter(storage: () => Storage, choice: UsageMeterChoice): void {
  try {
    storage().setItem(
      USAGE_METER_KEY,
      JSON.stringify({ order: choice.order, shown: choice.shown }),
    );
    if (choice.shown !== null) storage().removeItem(USAGE_BAR_HIDDEN_KEY);
  } catch {
    // Not remembered.
  }
}

// The local models whose weak-at-tools bar was dismissed with Don't show again (B116), by id.
export const WEAK_DISMISSED_KEY = "nest.local.weakDismissed";

export function loadWeakDismissed(storage: () => Storage): string[] {
  return loadNames(storage, WEAK_DISMISSED_KEY);
}

export function saveWeakDismissed(storage: () => Storage, ids: string[]): void {
  try {
    storage().setItem(WEAK_DISMISSED_KEY, JSON.stringify(ids));
  } catch {
    // Not remembered.
  }
}

// The Features groups the user opened (true) or closed (false) by hand (B103), by id; a
// group without a choice opens when it has something new.
export const FEATURE_GROUPS_KEY = "nest.features.groups";

export function loadFeatureGroups(storage: () => Storage): Record<string, boolean> {
  let saved: unknown;
  try {
    saved = JSON.parse(storage().getItem(FEATURE_GROUPS_KEY) ?? "{}");
  } catch {
    return {};
  }
  if (typeof saved !== "object" || saved === null || Array.isArray(saved)) return {};
  return Object.fromEntries(
    Object.entries(saved as Record<string, unknown>).filter(
      (entry): entry is [string, boolean] => typeof entry[1] === "boolean",
    ),
  );
}

export function saveFeatureGroups(storage: () => Storage, groups: Record<string, boolean>): void {
  try {
    storage().setItem(FEATURE_GROUPS_KEY, JSON.stringify(groups));
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

// Each project's All or Mine choice for its open issues on the start screen (B101), as the
// Mac keeps it per project; without one the daemon's per-repo default applies.
const ISSUE_SHOW_KEY = (repo: string) => `nest.issues.show.${repo}`;

export function loadIssueShow(storage: () => Storage, repo: string): IssueShow | null {
  try {
    const saved = storage().getItem(ISSUE_SHOW_KEY(repo));
    return saved === "all" || saved === "mine" ? saved : null;
  } catch {
    return null;
  }
}

export function saveIssueShow(storage: () => Storage, repo: string, show: IssueShow): void {
  try {
    storage().setItem(ISSUE_SHOW_KEY(repo), show);
  } catch {
    // Not remembered.
  }
}
