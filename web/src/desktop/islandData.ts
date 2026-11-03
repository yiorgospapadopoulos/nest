// The pill's inputs from the shared store and this device's seen marks (IslandStore.swift).
// The pill and the main window are two windows of one origin, so they share the marks
// through localStorage and hear each other's changes as `storage` events.
import type { GroupEntry, HabitRun } from "../api/types.ts";
import type { State } from "../store/state.ts";
import type { IslandChat, IslandOrder, IslandSnapshot } from "./island.ts";

export const SEEN_KEY = "nest.desktop.island.seen";
export const INSTALLED_KEY = "nest.desktop.island.installedAt";
export const ISLAND_SETTINGS_KEY = "nest.desktop.island.settings";

/** Island settings (Settings > Appearance, as the Mac's): shown, and in which order. */
export interface IslandSettings {
  shown: boolean;
  order: IslandOrder;
}

export function loadIslandSettings(storage: Storage): IslandSettings {
  try {
    const saved = JSON.parse(storage.getItem(ISLAND_SETTINGS_KEY) ?? "{}") as Partial<
      Record<keyof IslandSettings, unknown>
    >;
    return { shown: saved.shown !== false, order: saved.order === "oldest" ? "oldest" : "newest" };
  } catch {
    return { shown: true, order: "newest" };
  }
}

export function saveIslandSettings(storage: Storage, settings: IslandSettings): void {
  try {
    storage.setItem(ISLAND_SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // A blocked storage keeps the settings for this run only.
  }
}

export function loadSeen(storage: Storage): Record<string, number> {
  try {
    const saved = JSON.parse(storage.getItem(SEEN_KEY) ?? "{}") as Record<string, unknown>;
    return Object.fromEntries(
      Object.entries(saved).filter((entry): entry is [string, number] => Number.isFinite(entry[1])),
    );
  } catch {
    return {};
  }
}

/** The chat was seen now: its done pixies leave and those that need the user turn calm. */
export function markSeen(storage: Storage, session: string, now: number): void {
  try {
    storage.setItem(SEEN_KEY, JSON.stringify({ ...loadSeen(storage), [session]: now }));
  } catch {
    // A blocked storage only shows a seen pixie again.
  }
}

// A pixie that finishes in the focused chat lands on the pill for this long before the
// chat counts as seen and it leaves (D140: it flies, lands, then pops).
export const LAND_MS = 3000;

/**
 * How long the focused chat waits before it counts as seen, in ms: until its pixies that
 * just finished have landed, as the Mac's IslandController.see; at once otherwise.
 */
export function seenDelay(groups: GroupEntry[] | undefined, now: number): number {
  const finished = (groups ?? []).flatMap((group) =>
    group.calls.flatMap((call) => (call.finished_at == null ? [] : [Date.parse(call.finished_at)])),
  );
  if (finished.length === 0) return 0;
  return Math.min(LAND_MS, Math.max(0, Math.max(...finished) + LAND_MS - now));
}

/** When the pill first showed on this device, kept from the first call on. */
export function installedAt(storage: Storage, now: number): number {
  try {
    const saved = Number(storage.getItem(INSTALLED_KEY));
    if (Number.isFinite(saved) && saved > 0) return saved;
    storage.setItem(INSTALLED_KEY, String(now));
  } catch {
    // Without storage every start counts as the first.
  }
  return now;
}

/** Each habit's latest run that is not queued: its history when loaded, else its last run. */
export function latestRuns(state: State): HabitRun[] {
  return Object.values(state.habits).flatMap((habits) =>
    habits.flatMap((habit) => {
      const run = state.habitRuns[habit.id]?.find((r) => r.outcome !== "queued") ?? habit.last_run;
      return run === null || run.outcome === "queued" ? [] : [run];
    }),
  );
}

/** Project chats and pixies' own chats count as normal; habit runs do not. */
function chats(state: State): Record<string, IslandChat> {
  const own = new Set(Object.values(state.pixies).map((p) => p.chat_session_id));
  return Object.fromEntries(
    Object.values(state.sessions).map((s) => [
      s.id,
      {
        repo: s.repo,
        working: s.state === "running" || s.state === "starting",
        updatedAt: Date.parse(s.updated_at),
        normal: s.pixie_id == null || own.has(s.id),
      },
    ]),
  );
}

export function snapshotOf(
  state: State,
  marks: {
    seen: Record<string, number>;
    installedAt: number;
    awakeSince: number;
    settings: IslandSettings;
  },
  now: number,
): IslandSnapshot {
  const habitRuns = latestRuns(state);
  const agents = Object.fromEntries(
    [...Object.keys(state.pixieGroups), ...habitRuns.flatMap((r) => r.session_id ?? [])].map(
      (id) => [id, state.tracking[id]?.agents ?? []],
    ),
  );
  return {
    groups: state.pixieGroups,
    agents,
    approvals: Object.values(state.approvals),
    habitRuns,
    pixies: Object.values(state.pixies),
    teams: Object.values(state.teams),
    chats: chats(state),
    seen: marks.seen,
    installedAt: marks.installedAt,
    order: marks.settings.order,
    shown: marks.settings.shown,
    now,
    awakeSince: marks.awakeSince,
  };
}
