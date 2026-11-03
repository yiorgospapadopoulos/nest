import { useEffect, useRef } from "react";
import type { JsonObject, RepoConfig, RepoPatch } from "../../../api/types.ts";
import { useStore } from "../../../store/context.ts";
import { useApi } from "../../context.ts";
import { useSettingsChange } from "../config/util.ts";
import { createSettingsSaver } from "./saveQueue.ts";

export type SaveProject = (
  name: string,
  edit: (repo: RepoConfig) => RepoPatch,
  failure?: string,
) => void;

/**
 * Saves a project's settings in turn (audit BUG-102): `save(name, edit)` makes the patch
 * from the project as last saved; a failure says "Could not save the project settings".
 * The page makes one and hands it to its tabs, so all its changes share the one queue.
 */
export function useProjectSaver(): SaveProject {
  const api = useApi();
  const { state, actions } = useStore();
  const change = useSettingsChange();
  const repos = useRef(state.repos);
  useEffect(() => {
    repos.current = state.repos;
  });
  const saver = useRef<ReturnType<typeof createSettingsSaver> | null>(null);
  return (name, edit, failure = "Could not save the project settings") => {
    saver.current ??= createSettingsSaver(
      (project, patch) => api.updateRepo(project, patch),
      (project) => repos.current.find((r) => r.name === project),
      (repo) => {
        // Shown at once, as the daemon's own event will.
        actions.receive({
          id: null,
          ts: new Date().toISOString(),
          session_id: null,
          type: "repo.updated",
          payload: { repo: repo as unknown as JsonObject },
        });
      },
    );
    const queue = saver.current;
    change(failure, () => queue.change(name, edit));
  };
}
