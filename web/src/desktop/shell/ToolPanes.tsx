import { useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { ansiSpans } from "../../screens/chat/ansi.ts";
import { useStore } from "../../store/context.ts";
import { Fireflies } from "../../ui/Fireflies.tsx";
import { Icon } from "../../ui/Icon.tsx";
import type { LocalServer } from "../bridge.ts";
import { useBridge } from "../context.ts";
import { browserAddress, type ToolPane } from "../layout/tools.ts";
import { Button } from "../ui/controls.tsx";
import { MenuIcon } from "../ui/menuIcons.tsx";
import { Popover } from "../ui/Popover.tsx";
import { useShell } from "./context.ts";
import { browsers, BrowserSession } from "./toolSessions.ts";

/**
 * A browser pane's page: its window's label, kept while the pane is out of view
 * (toolSessions.ts), and how to open, move through and reload it.
 */
function useBrowser(pane: ToolPane) {
  const bridge = useBridge();
  const shell = useShell();
  const { actions } = useStore();
  const session = browsers.session(pane.id, () => new BrowserSession());
  // Cleared when its window closes, while the pane is out of view too (DesktopShell).
  const label = useSyncExternalStore(session.subscribe, () => session.label);
  const remember = (next: string | null) => {
    session.remember(next);
  };
  const open = (url: string) => {
    shell.update((s) => {
      s.setURL(url, pane.id);
    });
    // The pane's own window takes the page while it is open.
    bridge
      .openBrowserWindow(url, undefined, label ?? undefined)
      .then(remember, (error: unknown) => {
        actions.toast(error instanceof Error ? error.message : String(error), "error");
      });
  };
  // A window that was closed answers no more: the pane opens the page again on Reload.
  const on = (act: (label: string) => Promise<void>) => {
    if (label === null) return;
    act(label).catch(() => {
      remember(null);
    });
  };
  return {
    label,
    open,
    back: () => {
      on((l) => bridge.browserBack(l));
    },
    forward: () => {
      on((l) => bridge.browserForward(l));
    },
    reload: () => {
      if (label === null) {
        if (pane.url !== null) open(pane.url);
        return;
      }
      bridge.browserReload(label).catch(() => {
        remember(null);
        if (pane.url !== null) open(pane.url);
      });
    },
  };
}

/**
 * A browser pane, as the Mac's BrowserPaneView: back, forward, reload, the address field
 * and the local servers, then the page. Tauri cannot place a web view inside the split on
 * Linux yet (tauri#10420), so the page shows in a window of its own that the pane drives.
 */
export function BrowserPane({ pane }: { pane: ToolPane }) {
  const browser = useBrowser(pane);
  const [address, setAddress] = useState(pane.url ?? "");
  const [servers, setServers] = useState(false);
  const serversButton = useRef<HTMLButtonElement>(null);
  const go = (text: string) => {
    const url = browserAddress(text);
    if (url === null) return;
    setAddress(url);
    browser.open(url);
  };
  const opened = browser.label !== null;
  return (
    <div className="dk-browser">
      <div className="dk-btool">
        <button
          className="ib"
          aria-label="Back"
          title="Back"
          disabled={!opened}
          onClick={browser.back}
        >
          <Icon name="chevl" />
        </button>
        <button
          className="ib"
          aria-label="Forward"
          title="Forward"
          disabled={!opened}
          onClick={browser.forward}
        >
          <Icon name="chevr" />
        </button>
        <button
          className="ib"
          aria-label="Reload"
          title="Reload"
          disabled={pane.url === null}
          onClick={browser.reload}
        >
          <Icon name="restart" />
        </button>
        <form
          className="dk-url"
          onSubmit={(event) => {
            event.preventDefault();
            go(address);
          }}
        >
          <input
            aria-label="Address"
            placeholder="Address, localhost port or search"
            value={address}
            onChange={(event) => {
              setAddress(event.target.value);
            }}
          />
        </form>
        <button
          ref={serversButton}
          className="ib"
          aria-label="Local servers"
          title="Local servers"
          aria-expanded={servers}
          onClick={() => {
            setServers(!servers);
          }}
        >
          <ServerGlyph />
        </button>
        {servers && (
          <Popover
            anchor={serversButton}
            label="Local servers"
            className="dk-servers-pop"
            onClose={() => {
              setServers(false);
            }}
          >
            <LocalServerList
              onPick={(url) => {
                setServers(false);
                go(url);
              }}
            />
          </Popover>
        )}
      </div>
      {pane.url === null ? (
        <div className="dk-bstart">
          <MenuIcon name="globe" />
          <p>Type an address, a localhost port such as 3000, or pick a local server</p>
          <div className="dk-bstart-list">
            <LocalServerList onPick={go} />
          </div>
        </div>
      ) : (
        <div className="dk-bstart">
          <MenuIcon name="globe" />
          <p className="dk-baddr">{pane.url}</p>
          {!opened && (
            <Button
              kind="soft"
              onClick={() => {
                if (pane.url !== null) browser.open(pane.url);
              }}
            >
              Open window
            </Button>
          )}
        </div>
      )}
    </div>
  );
}

/** The Mac's server symbol, for the Local servers button. */
function ServerGlyph() {
  return (
    <svg className="ic" viewBox="0 0 16 16" aria-hidden="true">
      <rect x="2.5" y="2.5" width="11" height="4.6" rx="1.2" />
      <rect x="2.5" y="8.9" width="11" height="4.6" rx="1.2" />
      <path d="M5 4.8h.1M5 11.2h.1" />
    </svg>
  );
}

/** The ports listening on this computer's localhost, looked up each time the list shows. */
function LocalServerList({ onPick }: { onPick: (url: string) => void }) {
  const bridge = useBridge();
  const { address } = useStore();
  const [servers, setServers] = useState<LocalServer[] | null>(null);
  useEffect(() => {
    let live = true;
    // Nest's own daemon is no dev server.
    const daemonPort = Number(address.split(":").at(-1));
    bridge.localServers().then(
      (found) => {
        if (live) setServers(found.filter((s) => s.port !== daemonPort));
      },
      () => {
        if (live) setServers([]);
      },
    );
    return () => {
      live = false;
    };
  }, [bridge, address]);
  return (
    <div className="dk-servers">
      <p className="dk-servers-h">Local servers</p>
      {servers === null ? (
        <p className="dk-servers-note">
          <Fireflies size={10} />
          Looking for servers
        </p>
      ) : servers.length === 0 ? (
        <p className="dk-servers-note">Nothing is listening on localhost</p>
      ) : (
        servers.map((server) => (
          <button
            key={server.port}
            className="dk-server"
            onClick={() => {
              onPick(`http://localhost:${String(server.port)}`);
            }}
          >
            <MenuIcon name="globe" />
            <span className="dk-server-port">localhost:{server.port}</span>
            <span className="dk-server-proc">{server.process}</span>
          </button>
        ))
      )}
    </div>
  );
}

/** A folder's dev server output (B108), live from the daemon. */
export function RunPane({ pane }: { pane: ToolPane }) {
  const { state, actions } = useStore();
  const folder = pane.folder ?? "";
  const session = pane.session ?? "";
  const text = state.runOutput[folder] ?? "";
  const spans = useMemo(() => ansiSpans(text), [text]);
  const box = useRef<HTMLPreElement>(null);
  useEffect(() => {
    void actions.openRunOutput(session, folder);
    return () => {
      actions.closeRunOutput(folder);
    };
  }, [actions, session, folder]);
  useLayoutEffect(() => {
    const element = box.current;
    if (element !== null) element.scrollTop = element.scrollHeight;
  }, [spans]);
  return (
    <pre ref={box} className="dk-run rout" tabIndex={0} aria-label="Output">
      {spans.map((span, index) => (
        <span key={index} className={span.color === null ? undefined : `a${String(span.color)}`}>
          {span.text}
        </span>
      ))}
    </pre>
  );
}
