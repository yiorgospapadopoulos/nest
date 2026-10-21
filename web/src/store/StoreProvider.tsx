import { useEffect, useMemo, useReducer, type ReactNode } from "react";
import type { Api } from "../api/client.ts";
import { EventStream, eventsUrl, type SocketFactory } from "../api/events.ts";
import { browserPushEnv } from "../pwa/push.ts";
import { reportVisibility } from "../pwa/visibility.ts";
import { createActions } from "./actions.ts";
import {
  loadDrafts,
  loadFoldedTeams,
  loadShowAutomated,
  loadUsageBarHidden,
  saveDrafts,
} from "./devicePrefs.ts";
import { StoreContext } from "./context.ts";
import { deviceStorage } from "./legacyKeys.ts";
import { reduce } from "./reducer.ts";
import { initialState } from "./state.ts";

interface Props {
  api: Api;
  connect: SocketFactory;
  storage?: () => Storage;
  location?: { protocol: string; host: string };
  children: ReactNode;
}

/** Loads snapshots, then keeps them current from the event socket while paired. */
export function StoreProvider({
  api,
  connect,
  storage = deviceStorage,
  location = window.location,
  children,
}: Props) {
  const [state, dispatch] = useReducer(reduce, storage, (from) => ({
    ...initialState,
    showAutomated: loadShowAutomated(from),
    foldedTeams: loadFoldedTeams(from),
    usageBarHidden: loadUsageBarHidden(from),
    drafts: loadDrafts(from),
  }));
  const actions = useMemo(() => createActions(api, dispatch, storage), [api, storage]);
  const ready = state.auth === "ready";
  const drafts = state.drafts;

  useEffect(() => {
    saveDrafts(storage, drafts);
  }, [storage, drafts]);

  useEffect(() => {
    void actions.load();
  }, [actions]);

  useEffect(() => {
    if (!ready) return;
    const stream = new EventStream(connect, (after) => eventsUrl(location, after), {
      onEvent: (event) => {
        actions.receive(event);
        if (event.type === "claude_chats.updated") void actions.loadClaudeChats();
      },
      onOpen: (resumed) => {
        dispatch({ type: "reconnecting", on: false });
        // Without a cursor, events between the snapshot and the socket may be missing,
        // including those of the chat on screen. The Claude Code chat list changes with
        // ephemeral events only, so it reloads either way, as does a chat on screen whose
        // history failed to load.
        if (resumed) {
          void actions.loadClaudeChats();
          void actions.reloadFailed();
          void actions.reloadArtifacts();
        } else {
          void actions.resync();
        }
      },
      onLost: () => {
        dispatch({ type: "reconnecting", on: true });
      },
      onClosed: (reason) => {
        dispatch({ type: "auth", auth: reason === "unauthorized" ? "unpaired" : "forbidden" });
      },
    });
    // Back on screen or online again: no need to wait out the back-off.
    const wake = () => {
      if (document.visibilityState === "visible") stream.wake();
    };
    stream.start();
    document.addEventListener("visibilitychange", wake);
    window.addEventListener("online", wake);
    return () => {
      document.removeEventListener("visibilitychange", wake);
      window.removeEventListener("online", wake);
      stream.stop();
    };
  }, [ready, connect, location, actions]);

  useEffect(() => {
    if (!ready) return;
    return reportVisibility({ document, report: (visible) => api.reportVisibility(visible) });
  }, [ready, api]);

  // On launch and after pairing, so the daemon has this device's subscription.
  useEffect(() => {
    if (ready) void actions.refreshPush(browserPushEnv(window));
  }, [ready, actions]);

  const value = useMemo(() => ({ state, actions }), [state, actions]);
  return <StoreContext value={value}>{children}</StoreContext>;
}
