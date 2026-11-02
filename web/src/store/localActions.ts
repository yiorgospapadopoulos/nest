import type { Api } from "../api/client.ts";
import { LOCAL_MODELS_CHANGED } from "../api/events.ts";
import { localFailureOf, serverDownOf } from "../api/payloads.ts";
import type { LocalApp, NestEvent } from "../api/types.ts";
import { loadWeakDismissed, saveWeakDismissed } from "./devicePrefs.ts";
import type { LocalFailure } from "./local.ts";
import type { Action } from "./state.ts";

interface Tools {
  dispatch: (action: Action) => void;
  attempt: <T>(call: () => Promise<T>) => Promise<T | null>;
  quietly: <T>(call: () => Promise<T>) => Promise<T | null>;
  storage: () => Storage;
}

/**
 * Local models in chats (B106, B116 item 8): the list the model menus show, today's tokens,
 * the chats whose server did not answer, starting a server, and the weak-at-tools bars
 * dismissed on this device.
 */
export function localActions(api: Api, { dispatch, attempt, quietly, storage }: Tools) {
  let dismissed = loadWeakDismissed(storage);
  let starting: LocalApp[] = [];
  let hasModels = false;

  /** Quiet: without them the menus show the engines' models only. */
  async function loadLocalModels(): Promise<void> {
    const list = await quietly(() => api.localModels());
    if (list === null) return;
    hasModels = list.models.length > 0;
    dispatch({ type: "local", change: { list } });
  }

  async function loadLocalUsage(): Promise<void> {
    const usage = await quietly(() => api.localUsage());
    if (usage !== null) dispatch({ type: "local", change: { usage } });
  }

  const setStarting = (next: LocalApp[]) => {
    starting = next;
    dispatch({ type: "local", change: { starting } });
  };

  function localFailed(id: string, failure: LocalFailure | null): void {
    dispatch({ type: "localFailure", id, failure });
  }

  return {
    loadLocalModels,
    loadLocalUsage,
    localFailed,

    /** A refused send's local server, kept on the chat for its card; false for other errors. */
    sendRefusedLocally(id: string, error: unknown): boolean {
      const down = serverDownOf(error);
      if (down !== null) localFailed(id, down);
      return down !== null;
    },

    /** Starts the app's server on the Mac, then reads which models answer now. */
    async startLocalServer(app: LocalApp): Promise<void> {
      setStarting([...starting, app]);
      await attempt(() => api.startLocalServer(app));
      await loadLocalModels();
      setStarting(starting.filter((a) => a !== app));
    },

    /** Don't show again, for this model on this device. */
    dismissWeak(modelId: string): void {
      if (dismissed.includes(modelId)) return;
      dismissed = [...dismissed, modelId];
      saveWeakDismissed(storage, dismissed);
      dispatch({ type: "local", change: { weakDismissed: dismissed } });
    },

    /** The list changed; a turn failed on a local server, or a new one started; a turn ended. */
    receiveLocal(event: NestEvent): void {
      if (event.type === LOCAL_MODELS_CHANGED) {
        void loadLocalModels();
        return;
      }
      const id = event.session_id;
      if (event.type === "session.state" && id !== null) {
        const failure = localFailureOf(event.payload);
        if (failure !== null) localFailed(id, failure);
        else if (event.payload.state === "running" || event.payload.state === "starting") {
          localFailed(id, null);
        }
      }
      if (event.type === "session.result" && hasModels) void loadLocalUsage();
    },
  };
}
