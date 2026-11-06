// The projects' branch maps (B96), as NestKit's BranchMapStore: read when a picker or the
// map shows, kept with each branch's lane colour for the app's run, and each project's
// reload of its remotes (B131), which outlives the map being open.
import { useEffect, useSyncExternalStore } from "react";
import type { Api } from "../../api/client.ts";
import type { BranchMap, RemotesRefresh } from "../../api/types.ts";
import { useStore } from "../../store/context.ts";
import { useApi } from "../context.ts";
import { branchLanes, type BranchLanes } from "../shell/frame/branchLanes.ts";
import { LaneColors, laneColor, LANES, PlacePicker, type LaneMemory } from "./placePicker.ts";

export interface LoadedMap {
  map: BranchMap;
  picker: PlacePicker;
  // Every level, for the full tree; the small map shows `picker.lanes`.
  tree: BranchLanes;
  // A branch's lane colour, as CSS; null for a branch not on the map.
  color: (branch: string) => string | null;
}

const maps = new Map<string, LoadedMap>();
const colors = new Map<string, LaneColors>();
const listeners = new Set<() => void>();

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

const COLOURS_KEY = "nest.laneColors.";

/** `repo`'s lane colours in this browser's storage; blocked or bad storage only forgets them. */
function laneMemory(repo: string): LaneMemory {
  const key = `${COLOURS_KEY}${repo}`;
  const read = (): Record<string, number> => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) ?? "{}") as Record<string, unknown>;
      return Object.fromEntries(
        Object.entries(saved).filter(
          (entry): entry is [string, number] =>
            typeof entry[1] === "number" &&
            Number.isInteger(entry[1]) &&
            entry[1] > 0 &&
            entry[1] < LANES.length,
        ),
      );
    } catch {
      return {};
    }
  };
  return {
    saved: read(),
    save: (colours) => {
      try {
        localStorage.setItem(key, JSON.stringify(colours));
      } catch {
        // The colours are only given out again on the next start.
      }
    },
  };
}

/** Reads `repo`'s map again; a failed read keeps what was there. */
export async function loadBranchMap(api: Api, repo: string): Promise<void> {
  let map: BranchMap;
  try {
    map = await api.branchMap(repo);
  } catch {
    return;
  }
  const lanes = colors.get(repo) ?? new LaneColors(laneMemory(repo));
  colors.set(repo, lanes);
  lanes.assign(map);
  const names = new Set(map.branches.map((b) => b.name));
  maps.set(repo, {
    map,
    picker: new PlacePicker(map),
    tree: branchLanes(map),
    color: (branch) => (names.has(branch) ? laneColor(lanes.index(branch, map)) : null),
  });
  for (const listener of [...listeners]) listener();
}

/** `repo`'s branch map, read when this first shows; null until it is in, or without git. */
export function useBranchMap(repo: string, git: boolean): LoadedMap | null {
  const api = useApi();
  useEffect(() => {
    if (git) void loadBranchMap(api, repo);
  }, [api, repo, git]);
  const loaded = useSyncExternalStore(
    subscribe,
    () => maps.get(repo) ?? null,
    () => null,
  );
  return git ? loaded : null;
}

// A pick that changes the list slides another row under the pointer: a picked remote row
// goes, and a pick from Find brings the whole list back. The second click of a double click
// must not then pick a row the user never clicked, so the pause outlasts the slowest one.
const PICK_PAUSE_MS = 600;
const heldPicks = new Map<string, number>();

/** Whether `repo` is in such a pick or the pause after it: rows ignore clicks meanwhile. */
export function picksHeld(repo: string): boolean {
  return (heldPicks.get(repo) ?? 0) > Date.now();
}

/** Runs such a pick of `repo` unless one holds; a failed pick ends the hold the same way. */
export async function holdPicks(repo: string, pick: () => Promise<void>): Promise<void> {
  if (picksHeld(repo)) return;
  heldPicks.set(repo, Infinity);
  try {
    await pick();
  } finally {
    heldPicks.set(repo, Date.now() + PICK_PAUSE_MS);
  }
}

/** Remotes that failed the same way, with the reason. */
export interface RemoteFailure {
  remotes: string;
  reason: string;
}

export interface Reload {
  running: boolean;
  failures: RemoteFailure[];
  start: () => void;
  dismiss: () => void;
}

type ReloadState = Pick<Reload, "running" | "failures">;

const IDLE: ReloadState = { running: false, failures: [] };
const reloads = new Map<string, ReloadState>();

function setReload(repo: string, reload: ReloadState): void {
  reloads.set(repo, reload);
  for (const listener of [...listeners]) listener();
}

/** Each reason once, naming the remotes it hit. */
export function remoteFailures(report: RemotesRefresh): RemoteFailure[] {
  const byReason = new Map<string, string[]>();
  for (const { name, error } of report.remotes) {
    if (error !== null) byReason.set(error, [...(byReason.get(error) ?? []), name]);
  }
  return [...byReason].map(([reason, remotes]) => ({ remotes: remotes.join(", "), reason }));
}

/**
 * The project's reload: the map at once, since a dead remote can hold the fetch for minutes,
 * then the fetch, then the map again. The map stays usable throughout.
 */
export function useReload(repo: string): Reload {
  const api = useApi();
  const { actions } = useStore();
  const reload = useSyncExternalStore(
    subscribe,
    () => reloads.get(repo) ?? IDLE,
    () => IDLE,
  );
  const reread = async () => {
    await Promise.all([loadBranchMap(api, repo), actions.refreshRepo(repo)]);
  };
  const run = async () => {
    setReload(repo, { running: true, failures: [] });
    await reread();
    const report = await actions.refreshRemotes(repo);
    await reread();
    setReload(repo, { running: false, failures: report === null ? [] : remoteFailures(report) });
  };
  return {
    ...reload,
    start: () => {
      if (reloads.get(repo)?.running !== true) void run();
    },
    dismiss: () => {
      setReload(repo, IDLE);
    },
  };
}
