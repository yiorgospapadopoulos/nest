// The shown project's branch map (B96) for the sidebar: whether it is open, and the
// colours it gives the chats' branches.
import { useEffect, useLayoutEffect, useMemo, useRef } from "react";
import type { BranchMapBranch, RemoteBranch, RepoConfig } from "../../../api/types.ts";
import type { ChatPlace } from "../../../screens/chat/place.ts";
import { useStore } from "../../../store/context.ts";
import { chatStatus, pendingFor } from "../../../store/selectors.ts";
import {
  holdPicks,
  loadBranchMap,
  picksHeld,
  useBranchMap,
  type LoadedMap,
} from "../../chat/branchMaps.ts";
import { selectionOf } from "../../chat/placePicker.ts";
import { useApi } from "../../context.ts";
import { useShell } from "../context.ts";
import { branchChats, branchFor, type BranchChat } from "./branchLanes.ts";
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
        if (event.type === "repo.branches_changed" && event.payload.name === name) {
          void loadBranchMap(api, name);
          void actions.refreshRepo(name);
        }
      }),
    [actions, api, name],
  );
  useEffect(() => {
    if (git && !reconnecting) void loadBranchMap(api, name);
  }, [api, name, git, reconnecting]);
  return map;
}

/** Reads the map and the project's branch again each time `open` turns on. */
export function useFreshWhenOpen(repo: string, git: boolean, open: boolean): void {
  const { actions } = useStore();
  const api = useApi();
  useEffect(() => {
    if (!git || !open) return;
    void loadBranchMap(api, repo);
    void actions.refreshRepo(repo);
  }, [actions, api, repo, git, open]);
}

/**
 * One toast for a selected place the daemon reports gone (B131), then it is cleared there.
 * A name stays told until the project has a selection again, so the clear in flight, or a
 * list read before it landed, shows nothing twice.
 */
export function useGonePlaces(): void {
  const { state, actions } = useStore();
  const told = useRef(new Map<string, string>());
  useEffect(() => {
    for (const repo of state.repos) {
      const gone = repo.selected_place_gone;
      if (repo.selected_place !== null) told.current.delete(repo.name);
      if (gone === null || told.current.get(repo.name) === gone) continue;
      told.current.set(repo.name, gone);
      actions.toast(`${gone} is gone. New chats start in the project folder.`, "info");
      void actions.clearGonePlace(repo.name);
    }
  }, [actions, state.repos]);
}

/** Each branch's chat dot in `repo`. */
export function useBranchChats(repo: RepoConfig, map: LoadedMap): Map<string, BranchChat> {
  const { state } = useStore();
  return useMemo(
    () =>
      branchChats(
        map.map,
        Object.values(state.sessions).filter((s) => s.repo === repo.name && s.pixie_id == null),
        Object.values(state.claudeChats).filter((c) => c.repo === repo.name),
        repo,
        (s) => chatStatus(s, pendingFor(state, s.id)).tone,
      ),
    [map.map, repo, state],
  );
}

export interface MapActions {
  // Selects the row, making the local branch first for a remote-only one. Starts nothing.
  pick: (branch: BranchMapBranch) => void;
  // The same from Find: once the selection has landed the row is brought into view.
  pickFound: (branch: BranchMapBranch) => void;
  pickRemote: (remote: RemoteBranch) => void;
  // Back to the project folder.
  clear: () => void;
  // Opens a new chat's draft on a new worktree from the branch.
  addWorktree: (branch: string) => void;
}

/** What the map's rows do, the same across renders so the rows need not draw again. */
export function useMapActions(onLanded: () => void): MapActions {
  const { actions } = useStore();
  const shell = useShell();
  const api = useApi();
  const latest = useRef({ actions, shell, api, onLanded });
  useLayoutEffect(() => {
    latest.current = { actions, shell, api, onLanded };
  });
  return useMemo(() => {
    const project = () => latest.current.shell.repo.name;
    const track = async (remote: RemoteBranch) => {
      const { actions, api } = latest.current;
      const repo = project();
      const made = await actions.trackRemoteBranch(repo, remote.remote, remote.name);
      if (made === null) return;
      await Promise.all([loadBranchMap(api, repo), actions.selectPlace(repo, { branch: made })]);
      latest.current.onLanded();
    };
    const select = async (branch: BranchMapBranch) => {
      if (branch.remote !== null) await track({ remote: branch.remote, name: branch.name });
      else await latest.current.actions.selectPlace(project(), selectionOf(branch));
    };
    return {
      pick: (branch) => {
        if (branch.remote !== null) {
          void holdPicks(project(), () => select(branch));
        } else if (!picksHeld(project())) {
          void select(branch);
        }
      },
      pickFound: (branch) => {
        void holdPicks(project(), async () => {
          await select(branch);
          latest.current.onLanded();
        });
      },
      pickRemote: (remote) => {
        void holdPicks(project(), () => track(remote));
      },
      clear: () => {
        const { actions, shell } = latest.current;
        void actions.selectPlace(shell.repo.name, {});
      },
      addWorktree: (branch) => {
        latest.current.shell.newWorktreeFrom(branch);
      },
    };
  }, []);
}

/** The colour of the branch a chat's place is on, once the map has it. */
export function placeColor(map: LoadedMap | null, place: ChatPlace | null): string | null {
  if (map === null || place === null) return null;
  const branch = branchFor(map.map, place);
  return branch === undefined ? null : map.color(branch.name);
}
