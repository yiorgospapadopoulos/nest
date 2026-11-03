// The shown project's branch map (B96) for the sidebar: whether it is open, and the
// colours it gives the chats' branches.
import { useEffect } from "react";
import type { ChatPlace } from "../../../screens/chat/place.ts";
import { useStore } from "../../../store/context.ts";
import { loadBranchMap, useBranchMap, type LoadedMap } from "../../chat/branchMaps.ts";
import { useApi } from "../../context.ts";
import { useShell } from "../context.ts";
import { branchFor } from "./branchLanes.ts";
import { useRowOpen } from "./foldRows.ts";

/** Whether the project's branch map is open, kept while the app runs. */
export function useBranchMapOpen(project: string): [boolean, () => void] {
  return useRowOpen(`branch-map-${project}`, false);
}

/**
 * The project's branch map, read while the sidebar shows the project and again whenever its
 * branches change or the events reconnect; the chat rows colour their branches from it.
 */
export function useProjectMap(): LoadedMap | null {
  const { state, actions } = useStore();
  const shell = useShell();
  const api = useApi();
  const { name, git } = shell.repo;
  const map = useBranchMap(name, git);
  const reconnecting = state.reconnecting;
  useEffect(
    () =>
      actions.onEvent((event) => {
        if (event.type === "repo.branches_changed" && event.payload.repo === name) {
          void loadBranchMap(api, name);
        }
      }),
    [actions, api, name],
  );
  useEffect(() => {
    if (git && !reconnecting) void loadBranchMap(api, name);
  }, [api, name, git, reconnecting]);
  return map;
}

/** The colour of the branch a chat's place is on, once the map has it. */
export function placeColor(map: LoadedMap | null, place: ChatPlace | null): string | null {
  if (map === null || place === null) return null;
  const branch = branchFor(map.map, place);
  return branch === undefined ? null : map.color(branch.name);
}
