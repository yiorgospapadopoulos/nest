import type { Api } from "../api/client.ts";
import { UPDATES_CHANGED } from "../api/events.ts";
import { updatesOf } from "../api/payloads.ts";
import type { EngineUpdates, NestEvent } from "../api/types.ts";
import type { Action, Toast, UpdatesState } from "./state.ts";

interface Tools {
  dispatch: (action: Action) => void;
  attempt: <T>(call: () => Promise<T>) => Promise<T | null>;
  quietly: <T>(call: () => Promise<T>) => Promise<T | null>;
  toast: (text: string, tone?: Toast["tone"]) => void;
  restartAndWait: (call: () => Promise<unknown>) => Promise<"back" | "timeout" | null>;
}

/**
 * The engine updates: one check when the app opens, the state read on every connect and
 * followed through `updates.changed`, and the restarts that apply or undo an update, after
 * which the page loads again once the daemon answers.
 */
export function updateActions(
  api: Api,
  { dispatch, attempt, quietly, toast, restartAndWait }: Tools,
) {
  let checked = false;
  let known: EngineUpdates | null = null;

  const put = (change: Partial<UpdatesState>) => {
    dispatch({ type: "updates", change });
  };
  const putStatus = (status: EngineUpdates) => {
    known = status;
    put({ status });
  };
  const read = async () => {
    const status = await quietly(() => api.updates());
    if (status !== null) putStatus(status);
    return status;
  };
  const restart = async (
    kind: NonNullable<UpdatesState["restarting"]>,
    call: () => Promise<unknown>,
  ) => {
    put({ restarting: kind });
    const result = await restartAndWait(call);
    if (result === "back") {
      window.location.reload();
      return;
    }
    put({ restarting: null });
    if (result === "timeout") toast("Nest did not come back.", "error");
    await read();
  };

  return {
    /** Once for the life of the app, however often the store becomes ready. */
    async checkUpdates(): Promise<void> {
      if (checked) return;
      checked = true;
      const status = await quietly(() => api.checkUpdates());
      if (status !== null) putStatus(status);
    },

    /** After every connect. */
    async loadUpdates(): Promise<void> {
      await read();
    },

    /**
     * How many chats a restart would stop right now. Asked for each time, as
     * `updates.changed` does not follow turns starting and ending.
     */
    async busyChats(): Promise<number> {
      return (await read())?.busy_chats ?? known?.busy_chats ?? 0;
    },

    /**
     * `after` runs once the daemon took the relaunch, as the desktop app's handing over to
     * the new app; if it fails, the page waits for the daemon as without it.
     */
    relaunchUpdate: (after?: () => Promise<unknown>) =>
      restart("relaunch", async () => {
        const answer = await api.relaunchUpdate();
        await after?.().catch(() => undefined);
        return answer;
      }),
    undoUpdate: () => restart("undo", () => api.undoUpdate()),

    hideUpdateStrip: () => {
      put({ hidden: true });
    },

    async dismissUpdateNotice(): Promise<void> {
      const status = await attempt(() => api.dismissUpdateNotice());
      if (status !== null) putStatus(status);
    },

    /** Called with every live event. */
    updatesEvent(event: NestEvent): void {
      if (event.type !== UPDATES_CHANGED) return;
      const status = updatesOf(event.payload);
      if (status !== null) putStatus(status);
    },
  };
}
