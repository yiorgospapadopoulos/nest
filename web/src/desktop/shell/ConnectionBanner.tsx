import type { ReactNode } from "react";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Icon } from "../../ui/Icon.tsx";
import { bannerActions, bannerText, type ServiceState } from "../layout/connection.ts";
import { Button } from "../ui/controls.tsx";
import { MenuIcon } from "../ui/menuIcons.tsx";
import "./connection.css";
import type { Reconnect } from "./useReconnect.ts";

/** The Mac's warning triangle. */
function Warning() {
  return (
    <svg className="dk-cwarn" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M8 2.4 14.2 13H1.8z" />
      <path d="M8 6.4v3.2M8 11.3v.2" />
    </svg>
  );
}

/**
 * Under the tab strip while the daemon cannot be reached, as the Mac's ConnectionBanner:
 * what is wrong and when it tries again, Retry, Start Nest service, and under it how to
 * install the service when it is missing or why starting it failed.
 */
export function ConnectionBanner({ reconnect }: { reconnect: Reconnect }) {
  const { connection, service, retry, startService } = reconnect;
  const starting = service.kind === "starting";
  const text = bannerText(connection);
  if (text === null) return null;
  return (
    <div className="dk-cbanner" role="alert">
      <div className="dk-cline">
        {starting ? <Fireflies size={11} /> : <Warning />}
        <span>{starting ? "Starting the Nest service" : text}</span>
        {bannerActions(connection, service).map((action) =>
          action === "retry" ? (
            <Button key={action} onClick={retry}>
              Retry
            </Button>
          ) : (
            <Button
              key={action}
              kind="primary"
              title="Start or restart the Nest daemon's background service"
              onClick={startService}
            >
              Start Nest service
            </Button>
          ),
        )}
      </div>
      <ServiceNote state={service} />
    </div>
  );
}

function ServiceNote({ state }: { state: ServiceState }) {
  if (state.kind === "notInstalled") {
    return (
      <Note>
        <p className="dk-cnote-t">
          The Nest service is not installed. Install it once in Terminal:
        </p>
        <div className="dk-ccmd">
          <code>{state.command}</code>
          <Button
            size="large"
            title="Copy the command"
            onClick={() => {
              void navigator.clipboard.writeText(state.command);
            }}
          >
            <MenuIcon name="copy" />
            Copy
          </Button>
        </div>
        <p className="dk-cnote-m">Then choose Start Nest service again.</p>
      </Note>
    );
  }
  if (state.kind === "failed") {
    return (
      <Note>
        <p className="dk-cfail">
          <Warning />
          <span>{state.reason}</span>
        </p>
      </Note>
    );
  }
  return null;
}

function Note({ children }: { children: ReactNode }) {
  return <div className="dk-cnote">{children}</div>;
}

/** The middle of a window with nothing to show yet, as the Mac's NoProjectView. */
export function Connecting() {
  return (
    <div className="dk-connecting">
      <Icon name="folder" />
      <p>Connecting to Nest</p>
    </div>
  );
}
