// The projects' branch maps (B96), as NestKit's BranchMapStore: read when a picker or the
// map shows, kept with each branch's lane colour for the app's run.
import { useEffect, useSyncExternalStore } from "react";
import type { Api } from "../../api/client.ts";
import type { BranchMap } from "../../api/types.ts";
import { useApi } from "../context.ts";
import { LaneColors, laneColor, PlacePicker } from "./placePicker.ts";

export interface LoadedMap {
  map: BranchMap;
  picker: PlacePicker;
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

/** Reads `repo`'s map again; a failed read keeps what was there. */
export async function loadBranchMap(api: Api, repo: string): Promise<void> {
  let map: BranchMap;
  try {
    map = await api.branchMap(repo);
  } catch {
    return;
  }
  const lanes = colors.get(repo) ?? new LaneColors();
  colors.set(repo, lanes);
  lanes.assign(map);
  const names = new Set(map.branches.map((b) => b.name));
  maps.set(repo, {
    map,
    picker: new PlacePicker(map),
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
