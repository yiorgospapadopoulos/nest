import type { RepoConfig, RepoPatch } from "../../../api/types.ts";

/**
 * A project's settings saves, as NestKit's AppStore.saveSettings (audit BUG-102): they run
 * one at a time per project, each change made against the settings the last save returned,
 * and only what it changed is sent. A change resolves with the project as saved, the
 * project unchanged when there was nothing to send, or null when the project is gone.
 */
export function createSettingsSaver(
  send: (name: string, patch: RepoPatch) => Promise<RepoConfig>,
  // The project as the app shows it now.
  current: (name: string) => RepoConfig | undefined,
  saved: (repo: RepoConfig) => void,
) {
  const queues = new Map<string, Promise<unknown>>();
  // What the latest save returned while saves wait in turn, newer than what is shown.
  const latest = new Map<string, RepoConfig>();

  return {
    change(name: string, edit: (repo: RepoConfig) => RepoPatch): Promise<RepoConfig | null> {
      const before = queues.get(name) ?? Promise.resolve();
      const run = before
        .catch(() => undefined)
        .then(async () => {
          const repo = latest.get(name) ?? current(name);
          if (repo === undefined) return null;
          const patch = edit(repo);
          if (Object.keys(patch).length === 0) return repo;
          const after = await send(name, patch);
          latest.set(name, after);
          saved(after);
          return after;
        });
      queues.set(name, run);
      void run
        .catch(() => undefined)
        .then(() => {
          if (queues.get(name) === run) {
            queues.delete(name);
            latest.delete(name);
          }
        });
      return run;
    },
  };
}
