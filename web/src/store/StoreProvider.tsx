import { useEffect, useMemo, useReducer, type ReactNode } from "react";
import type { Api } from "../api/client.ts";
import { EventStream, eventsUrl, type SocketFactory } from "../api/events.ts";
import { reportVisibility } from "../pwa/visibility.ts";
import { createActions } from "./actions.ts";
import { loadShowAutomated } from "./devicePrefs.ts";
import { StoreContext } from "./context.ts";
import { reduce } from "./reducer.ts";
import { initialState } from "./state.ts";

const browserStorage = () => window.localStorage;

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
  storage = browserStorage,
  location = window.location,
  children,
}: Props) {
  const [state, dispatch] = useReducer(reduce, storage, (from) => ({
    ...initialState,
    showAutomated: loadShowAutomated(from),
  }));
  const actions = useMemo(() => createActions(api, dispatch, storage), [api, storage]);
  const ready = state.auth === "ready";

  useEffect(() => {
    void actions.load();
  }, [actions]);

  useEffect(() => {
    if (!ready) return;
    const stream = new EventStream(connect, (after) => eventsUrl(location, after), {
      onEvent: (event) => {
        dispatch({ type: "event", event });
        if (event.type === "claude_chats.updated") void actions.loadClaudeChats();
      },
      onOpen: (resumed) => {
        // Without a cursor, events between the snapshot and the socket may be missing,
        // including those of the chat on screen.
        if (!resumed) void actions.resync();
      },
      onClosed: (reason) => {
        dispatch({ type: "auth", auth: reason === "unauthorized" ? "unpaired" : "forbidden" });
      },
    });
    stream.start();
    return () => {
      stream.stop();
    };
  }, [ready, connect, location, actions]);

  useEffect(() => {
    if (!ready) return;
    return reportVisibility({ document, report: (visible) => api.reportVisibility(visible) });
  }, [ready, api]);

  const value = useMemo(() => ({ state, actions }), [state, actions]);
  return <StoreContext value={value}>{children}</StoreContext>;
}
