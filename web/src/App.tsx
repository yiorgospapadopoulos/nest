import type { ReactNode } from "react";
import type { Api } from "./api/client.ts";
import type { SocketFactory } from "./api/events.ts";
import { AppearanceProvider } from "./appearance/AppearanceProvider.tsx";
import { Pairing } from "./screens/Pairing.tsx";
import { Shell } from "./screens/Shell.tsx";
import { useStore } from "./store/context.ts";
import { StoreProvider } from "./store/StoreProvider.tsx";
import { Toast } from "./ui/Toast.tsx";
import { usePauseWhenHidden } from "./ui/visible.ts";

interface Props {
  api: Api;
  connect: SocketFactory;
  storage?: () => Storage;
  location?: { protocol: string; host: string };
}

export function App({ api, connect, storage, location }: Props) {
  usePauseWhenHidden();
  return (
    <AppearanceProvider {...(storage === undefined ? {} : { storage })}>
      <StoreProvider
        api={api}
        connect={connect}
        {...(storage === undefined ? {} : { storage })}
        {...(location === undefined ? {} : { location })}
      >
        <div className="app">
          <Root />
          <div className="topfade" aria-hidden="true" />
          <Reconnecting />
        </div>
        <Toast />
      </StoreProvider>
    </AppearanceProvider>
  );
}

function Root() {
  const { state, actions } = useStore();
  switch (state.auth) {
    case "loading":
      return <main className="center" aria-busy="true" aria-label="Loading" />;
    case "unpaired":
      return <Pairing />;
    case "forbidden":
      return (
        <Notice title="This address is not allowed">
          Add it to <code>server.allowed_origins</code> in the daemon settings on{" "}
          {state.machine ?? "your Mac"}.
        </Notice>
      );
    case "offline":
      return (
        <Notice title={`Can't reach ${state.machine ?? "your Mac"}`}>
          {state.machine === null ? (
            "Check that the Mac is awake and Nest is running."
          ) : (
            <>
              Check that {state.machine} is awake, Nest is running there and{" "}
              <code>tailscale serve</code> is on.
            </>
          )}
          <button className="b b-pri" onClick={() => void actions.retry()}>
            Try again
          </button>
        </Notice>
      );
    case "ready":
      return <Shell />;
  }
}

/**
 * A small note while the live connection to the Mac is being restored. The status region
 * stays in place, as VoiceOver often misses one inserted together with its text.
 */
function Reconnecting() {
  const { state } = useStore();
  return (
    <div role="status">{state.reconnecting && <p className="reconn gl">Reconnecting...</p>}</div>
  );
}

function Notice({ title, children }: { title: string; children: ReactNode }) {
  return (
    <main className="center">
      <section className="pair gl" aria-label={title}>
        <h1>{title}</h1>
        <p>{children}</p>
      </section>
    </main>
  );
}
