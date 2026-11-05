import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, HttpApi, type Api } from "../api/client.ts";
import { browserSockets, type SocketFactory } from "../api/events.ts";
import { AppearanceProvider } from "../appearance/AppearanceProvider.tsx";
import { useStore } from "../store/context.ts";
import { DRAFTS_KEY } from "../store/devicePrefs.ts";
import { deviceStorage } from "../store/legacyKeys.ts";
import { StoreProvider } from "../store/StoreProvider.tsx";
import { connectionLost } from "../store/updates.ts";
import { DesktopToast } from "./ui/Toast.tsx";
import type { Bridge, DaemonConnection } from "./bridge.ts";
import { ApiContext, BridgeContext } from "./context.ts";
import { TranscriptPage } from "./chat/TranscriptPage.tsx";
import type { TranscriptTarget } from "./chat/transcriptTarget.ts";
import { Pill } from "./Pill.tsx";
import { ConnectionBanner, Connecting } from "./shell/ConnectionBanner.tsx";
import { DesktopShell } from "./shell/DesktopShell.tsx";
import { useReconnect } from "./shell/useReconnect.ts";
import { WindowButtons } from "./shell/WindowButtons.tsx";

type Refresh = () => Promise<"changed" | "same">;

function forgetDrafts(storage: () => Storage) {
  try {
    storage().removeItem(DRAFTS_KEY);
  } catch {
    // A blocked storage kept nothing either.
  }
}

export interface Daemon {
  api: Api;
  connect: SocketFactory;
}

const httpDaemon = (found: DaemonConnection): Daemon => ({
  api: new HttpApi(undefined, { base: found.base, token: found.token ?? "" }),
  connect: browserSockets(found.token),
});

/** Whether the daemon answers at all; a refusal is an answer. */
async function answers(api: Api): Promise<boolean> {
  try {
    await api.health();
    return true;
  } catch (error) {
    return error instanceof ApiError;
  }
}

/**
 * The window from launch: until the daemon answers, its frame with the connection banner,
 * trying again with the Mac's backoff (the token comes from the running daemon, so there
 * is none before); then the app, built again whenever the daemon gives a new token.
 */
export function DesktopRoot({
  bridge,
  pill = false,
  transcript = null,
  open = httpDaemon,
  storage,
}: {
  bridge: Bridge;
  pill?: boolean;
  // One chat's transcript alone, for a pane in the Mac app (B124).
  transcript?: TranscriptTarget | null;
  // The daemon's API and event socket at an address; tests give fakes.
  open?: (found: DaemonConnection) => Daemon;
  storage?: () => Storage;
}) {
  // Unsent text lives only while the app runs, as the Mac's DraftBook: the shared store
  // keeps it on the device, so the window forgets it at launch. The pill only reads it.
  useState(() => {
    if (!pill && transcript === null) forgetDrafts(storage ?? deviceStorage);
  });
  const [daemon, setDaemon] = useState<DaemonConnection | null>(null);
  const current = useRef<DaemonConnection | null>(null);
  const adopt = useCallback((found: DaemonConnection) => {
    const now = current.current;
    if (now !== null && now.base === found.base && now.token === found.token) return false;
    current.current = found;
    setDaemon(found);
    return true;
  }, []);
  const refresh = useCallback<Refresh>(
    async () => (adopt(await bridge.daemon()) ? "changed" : "same"),
    [bridge, adopt],
  );
  const found = useCallback(async () => {
    const next = await bridge.daemon();
    if (!(await answers(open(next).api))) return false;
    adopt(next);
    return true;
  }, [bridge, adopt, open]);
  const app = useMemo(() => {
    if (daemon === null) return null;
    const url = new URL(daemon.base);
    return { ...open(daemon), location: { protocol: url.protocol, host: url.host } };
  }, [daemon, open]);
  if (daemon === null || app === null) {
    return (
      <BridgeContext value={bridge}>
        <Launch pill={pill || transcript !== null} found={found} />
      </BridgeContext>
    );
  }
  return (
    <DesktopApp
      key={`${daemon.base} ${daemon.token ?? ""}`}
      bridge={bridge}
      api={app.api}
      connect={app.connect}
      location={app.location}
      pill={pill}
      transcript={transcript}
      refresh={refresh}
      {...(storage === undefined ? {} : { storage })}
    />
  );
}

/** Before the daemon first answers: the frame and the banner; a small window stays empty. */
function Launch({ pill, found }: { pill: boolean; found: () => Promise<boolean> }) {
  const reconnect = useReconnect(true, found);
  if (pill) return null;
  return (
    <>
      <div className="dk">
        <Frame>
          <Connecting />
        </Frame>
      </div>
      <div className="dk-banners">
        <ConnectionBanner reconnect={reconnect} />
      </div>
    </>
  );
}

interface Props {
  bridge: Bridge;
  api: Api;
  connect: SocketFactory;
  location: { protocol: string; host: string };
  storage?: () => Storage;
  // The pixie pill's window instead of the main one.
  pill?: boolean;
  // One chat's transcript instead of the main window.
  transcript?: TranscriptTarget | null;
  // Asks the platform for the daemon's token again; "changed" builds the app again.
  refresh?: Refresh;
}

const same: Refresh = () => Promise.resolve("same");

/** The desktop window (B117): the Mac's layout over the same store as the phone app. */
export function DesktopApp({
  bridge,
  api,
  connect,
  location,
  storage,
  pill = false,
  transcript = null,
  refresh = same,
}: Props) {
  return (
    <BridgeContext value={bridge}>
      <ApiContext value={api}>
        <AppearanceProvider {...(storage === undefined ? {} : { storage })}>
          <StoreProvider
            api={api}
            connect={connect}
            location={location}
            {...(storage === undefined ? {} : { storage })}
            {...(transcript !== null ? { pane: paneChat(transcript) } : {})}
          >
            {transcript !== null ? (
              <PaneRoot target={transcript} api={api} refresh={refresh} />
            ) : pill ? (
              <PillRoot />
            ) : (
              <>
                <div className="dk">
                  <Root refresh={refresh} />
                </div>
                <div className="dk-banners">
                  <DaemonBanner api={api} refresh={refresh} />
                  <DesktopToast />
                </div>
              </>
            )}
          </StoreProvider>
        </AppearanceProvider>
      </ApiContext>
    </BridgeContext>
  );
}

const paneChat = (target: TranscriptTarget) => {
  if ("chat" in target) return target.chat;
  return "claude" in target ? target.claude : target.work.session;
};

// How often a pane asks the app for a token again after the daemon refused one.
const TOKEN_RETRY_MS = 3000;

/** A transcript pane: nothing of the window around it, and it finds the daemon by itself. */
function PaneRoot({
  target,
  api,
  refresh,
}: {
  target: TranscriptTarget;
  api: Api;
  refresh: Refresh;
}) {
  const { state } = useStore();
  useDaemonReconnect(api, refresh);
  const refused = state.auth === "unpaired";
  useEffect(() => {
    if (!refused) return;
    const timer = window.setInterval(() => void refresh(), TOKEN_RETRY_MS);
    return () => {
      window.clearInterval(timer);
    };
  }, [refused, refresh]);
  return <TranscriptPage target={target} />;
}

function Root({ refresh }: { refresh: Refresh }) {
  const { state, actions, address } = useStore();
  // A token the daemon refused may be an old one: the daemon is asked for it again first.
  const tryAgain = () => {
    void refresh().then(
      (result) => {
        if (result === "same") void actions.retry();
      },
      () => void actions.retry(),
    );
  };
  switch (state.auth) {
    case "loading":
      return <Notice title="" busy />;
    case "unpaired":
      return (
        <Notice title="Nest did not accept this app">
          The daemon at <code>{address}</code> refused this app&apos;s token. Check that Nest runs
          as your user, then try again.
          <button className="b b-pri" onClick={tryAgain}>
            Try again
          </button>
        </Notice>
      );
    case "forbidden":
      return (
        <Notice title="This app is not allowed">
          The daemon at <code>{address}</code> refused the app&apos;s origin.
        </Notice>
      );
    case "offline":
      return (
        <Frame>
          <Connecting />
        </Frame>
      );
    case "ready":
      return <DesktopShell />;
  }
}

/** The pill shows only once the store is ready; it stays hidden otherwise. */
function PillRoot() {
  const { state } = useStore();
  return state.auth === "ready" ? <Pill /> : null;
}

/** The window while no shell shows: an empty strip to move it by, and its buttons. */
function Frame({ children }: { children: ReactNode }) {
  return (
    <div className="dk-notice">
      <div className="dk-tabs" data-tauri-drag-region>
        <span className="grow" data-tauri-drag-region />
        <WindowButtons />
      </div>
      {children}
    </div>
  );
}

function Notice({
  title,
  busy,
  children,
}: {
  title: string;
  busy?: boolean;
  children?: ReactNode;
}) {
  return (
    <Frame>
      <main
        className="center"
        aria-busy={busy === true}
        aria-label={busy === true ? "Loading" : title}
      >
        {busy !== true && (
          <section className="pair gl" aria-label={title}>
            <h1>{title}</h1>
            <p>{children}</p>
          </section>
        )}
      </main>
    </Frame>
  );
}

/**
 * The Mac's ConnectionBanner over the window while the daemon cannot be reached: after a
 * failed first load, or once the event socket dropped. When the daemon answers again the
 * app loads again (with a new token, if the daemon gives one), or the socket reconnects
 * at once rather than after its own wait.
 */
function DaemonBanner({ api, refresh }: { api: Api; refresh: Refresh }) {
  return <ConnectionBanner reconnect={useDaemonReconnect(api, refresh)} />;
}

function useDaemonReconnect(api: Api, refresh: Refresh) {
  const { state, actions } = useStore();
  const offline = state.auth === "offline";
  const lost = state.auth === "ready" && connectionLost(state);
  return useReconnect(offline || lost, async () => {
    if ((await refresh()) === "changed") return true;
    if (!(await answers(api))) return false;
    if (offline) await actions.retry();
    // The event socket's wake (StoreProvider): it reconnects now, not after its back-off.
    else window.dispatchEvent(new Event("online"));
    return true;
  });
}
