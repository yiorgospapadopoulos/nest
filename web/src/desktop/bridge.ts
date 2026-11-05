/*
 * The desktop shell's one door to the platform (B117): the Tauri app on Linux (later
 * Windows), or a browser stub for development and tests.
 *
 * The Tauri side's contract is desktop/src-tauri/src/commands.rs. With withGlobalTauri on,
 * calls go through `window.__TAURI__.core.invoke` and events through
 * `window.__TAURI__.event.listen`; arguments are snake_case and errors plain strings:
 *
 *   get_daemon                                  -> { base_url, token }
 *   pty_spawn { id, cwd?, cols, rows }          -> id; listen first to "pty://<id>" (text)
 *                                                  and "pty://<id>/exit" ({ code })
 *   pty_write { id, data }, pty_resize { id, cols, rows }, pty_kill { id }
 *   open_browser_window { url, title?, label? } -> the window's label; with the label of a
 *                                                  window still open, the page shows there
 *   browser_back / browser_forward / browser_reload { label }  on that browser window
 *   local_servers                               -> [{ port, process }] listening on localhost
 *   start_service                               -> "started" or "not_installed" (no user unit)
 *   pick_folder                                 -> the chosen folder's path, or null
 *   open_external { url }                       http, https or mailto, in the system's app
 *   open_path { path, reveal? }                 in the home folder: a folder, or reveal an item
 *   open_text_file { path, root }               a regular file inside root, in the text editor
 *   save_file { suggested_name, data_base64 | text } -> the saved path, or null
 *   notify { title, body, chat?, sound? }       a click emits "nest://open" { chat } to main
 *   window_control { action: minimize | toggle_maximize | close | start_drag | quit }
 *   window_state                                -> { minimized, visible } of the calling window
 *   show_main, pill_update { visible?, width?, height?, room? }
 *   pill_pointer                                -> [x, y] of the pointer in the pill window, or null
 *   get_settings / set_settings { keep_pill_on_top?, start_at_login?, disable_dmabuf_renderer? }
 *   events to the main window: "nest://new-chat", "nest://open-settings" (tray menu), and
 *   "nest://open" (OpenTarget) which the pill sends with event.emitTo("main", ...)
 *   (core:event:allow-emit-to, part of core:default), and "nest://browser-closed" (the
 *   window's label) when a browser window closes
 */

export interface DaemonConnection {
  // Such as "http://127.0.0.1:8765", without a trailing slash.
  base: string;
  // Null when none is known, as in a browser stub opened without one.
  token: string | null;
}

export interface LinuxSettings {
  // Runs Nest through XWayland on Wayland, so the pill stays on top; from the next start.
  keepPillOnTop: boolean;
  startAtLogin: boolean;
}

export interface Pty {
  write(data: string): void;
  resize(cols: number, rows: number): void;
  kill(): void;
}

export interface PtyHandlers {
  onOutput(data: string): void;
  onExit(code: number): void;
}

export interface LocalServer {
  port: number;
  // The process name, as the system lists it.
  process: string;
}

export type TrayEvent = "new-chat" | "open-settings";

/**
 * Where a click on the pill takes the main window: a chat (in its project), a pixie's own
 * chat on its page, a habit run's chat, or just Nest as it was.
 */
export type OpenTarget =
  // `approval`: open with that approval in view, the activity panel on Needs you.
  { chat: string; approval?: string } | { pixie: string } | { habitRun: string } | { home: true };

// The event the pill sends the main window ("main" is its window label).
export const OPEN_EVENT = "nest://open";
export const BROWSER_CLOSED_EVENT = "nest://browser-closed";

export interface Bridge {
  // Whether this runs in the desktop app; the browser stub has no shell or windows.
  native: boolean;
  // In a pane of the Mac app: its way to the app around it.
  pane?: PanePost;
  daemon(): Promise<DaemonConnection>;
  // Starts or restarts the daemon's user service; "not_installed" without its unit.
  startService(): Promise<"started" | "not_installed">;
  // The browser window's label, for back, forward and reload on it. With `label`, that
  // window shows the page and comes forward while it is still open.
  openBrowserWindow(url: string, title?: string, label?: string): Promise<string | null>;
  // A browser window closed: its label. Returns the unsubscribe.
  onBrowserClosed(callback: (label: string) => void): () => void;
  browserBack(label: string): Promise<void>;
  browserForward(label: string): Promise<void>;
  browserReload(label: string): Promise<void>;
  // The dev servers listening on this computer's localhost, by port.
  localServers(): Promise<LocalServer[]>;
  // The system's folder dialog over the window; null when cancelled or without one.
  pickFolder(): Promise<string | null>;
  spawnPty(
    id: string,
    options: { cwd: string | null; cols: number; rows: number },
    handlers: PtyHandlers,
  ): Promise<Pty>;
  // A web or mail link in the system's browser or mail app (http, https and mailto only).
  openExternal(url: string): Promise<void>;
  // A folder in the file manager, or with `reveal` an item shown in its folder; home only.
  openPath(path: string, reveal?: boolean): Promise<void>;
  // A regular file inside `root`, in the system's default text editor, never run. `path` is
  // untrusted, from a message: the Tauri side checks it and rejects anything else.
  openTextFile(path: string, root: string): Promise<void>;
  // The save dialog, then the file written there; the saved path, or null when cancelled.
  saveFile(
    suggestedName: string,
    contents: { text: string } | { base64: string },
  ): Promise<string | null>;
  // `chat`: the session a click on it opens; Tauri emits nest://open { chat } then.
  // `sound`: the system's message sound with it.
  notify(title: string, body: string, chat?: string, sound?: boolean): Promise<void>;
  minimize(): Promise<void>;
  toggleMaximize(): Promise<void>;
  close(): Promise<void>;
  startDrag(): Promise<void>;
  showMain(): Promise<void>;
  // The pill window: what takes clicks (width by height, centred at the top), how tall the
  // window is (room, at least height) and whether it shows; Nest keeps it at the top centre.
  pillUpdate(change: {
    visible?: boolean;
    width?: number;
    height?: number;
    room?: number;
  }): Promise<void>;
  // Where the pointer is in the pill's window (CSS px from its top left), as the window
  // system says; null outside it or when it cannot tell.
  pillPointer(): Promise<{ x: number; y: number } | null>;
  // The tray menu's items; returns the unsubscribe.
  onTray(event: TrayEvent, callback: () => void): () => void;
  // From the pill: brings the main window forward and asks it to show `target`.
  openInMain(target: OpenTarget): Promise<void>;
  // In the main window: what the pill asks it to show; returns the unsubscribe.
  onOpenRequest(callback: (target: OpenTarget) => void): () => void;
  // When the window moves or resizes, for the strip's gap under the pill.
  onWindowMoved(callback: () => void): () => void;
  // Whether the calling window is minimised or hidden, as the window manager says; null
  // when it cannot tell (an older Tauri side, or the browser stub).
  windowState(): Promise<{ minimized: boolean; visible: boolean } | null>;
  settings(): Promise<LinuxSettings>;
  setSettings(change: Partial<LinuxSettings>): Promise<LinuxSettings>;
}

type Unlisten = () => void;

interface TauriGlobal {
  core: { invoke(command: string, args?: Record<string, unknown>): Promise<unknown> };
  event: {
    listen(event: string, handler: (message: { payload: unknown }) => void): Promise<Unlisten>;
    // In every Tauri 2 window; optional so pages and tests that only listen can omit it.
    emitTo?: (target: string, event: string, payload?: unknown) => Promise<void>;
  };
}

/**
 * What a transcript pane's page asks of the Mac app (B124). The app checks each one
 * (WebPaneBridge.swift); `daemon` answers with the connection, all others with nothing.
 */
export type PaneMessage =
  | { kind: "daemon" }
  | { kind: "ready" }
  | { kind: "openExternal"; url: string }
  | { kind: "openFile"; path: string }
  | { kind: "open"; target: OpenTarget }
  | { kind: "copy"; text: string }
  | { kind: "toast"; text: string; tone: string }
  | { kind: "teamWork"; team: string }
  | { kind: "pixieWork"; pixie: string }
  | { kind: "message"; action: "edit" | "rewind" | "fork"; event: number }
  | { kind: "artifact"; id: string; version: number | null }
  | { kind: "terminal"; command: string }
  | { kind: "image"; id: string }
  | { kind: "saveFile"; name: string; base64: string };

export type PanePost = (message: PaneMessage) => Promise<unknown>;

declare global {
  interface Window {
    __TAURI__?: TauriGlobal;
    webkit?: { messageHandlers?: { nestPane?: { postMessage: PanePost } } };
  }
}

const SAFE_SCHEMES = new Set(["http:", "https:", "mailto:"]);

/** A web or mail link the app may open outside itself (the Mac's SafeLink), else null. */
export function safeLink(text: string): string | null {
  try {
    const url = new URL(text);
    return SAFE_SCHEMES.has(url.protocol) ? url.href : null;
  } catch {
    return null;
  }
}

/** A pty id the Tauri side accepts (letters, digits, - and _, at most 64), from a pane id. */
export function ptyId(paneId: string): string {
  return paneId.replace(/[^A-Za-z0-9_-]/g, "-").slice(0, 64);
}

function trimmed(base: string): string {
  return base.replace(/\/+$/, "");
}

interface SavedSettings {
  keep_pill_on_top: boolean;
  start_at_login: boolean;
}

const fromSaved = (saved: SavedSettings): LinuxSettings => ({
  keepPillOnTop: saved.keep_pill_on_top,
  startAtLogin: saved.start_at_login,
});

export function tauriBridge(tauri: TauriGlobal): Bridge {
  const invoke = (command: string, args?: Record<string, unknown>) =>
    tauri.core.invoke(command, args);
  const control = async (action: string) => {
    await invoke("window_control", { action });
  };

  /** Listens until the returned function is called, even if that comes before listen settles. */
  const listen = (event: string, handler: (payload: unknown) => void) => {
    let gone = false;
    const ready = tauri.event.listen(event, (message) => {
      if (!gone) handler(message.payload);
    });
    const off = () => {
      gone = true;
      void ready.then((unlisten) => {
        unlisten();
      });
    };
    return { ready, off };
  };

  return {
    native: true,
    async daemon() {
      const found = (await invoke("get_daemon")) as { base_url: string; token: string };
      return { base: trimmed(found.base_url), token: found.token };
    },
    async startService() {
      return (await invoke("start_service")) === "not_installed" ? "not_installed" : "started";
    },
    async openBrowserWindow(url, title, label) {
      return (await invoke("open_browser_window", {
        url,
        ...(title === undefined ? {} : { title }),
        ...(label === undefined ? {} : { label }),
      })) as string;
    },
    onBrowserClosed(callback) {
      return listen(BROWSER_CLOSED_EVENT, (payload) => {
        callback(String(payload));
      }).off;
    },
    async browserBack(label) {
      await invoke("browser_back", { label });
    },
    async browserForward(label) {
      await invoke("browser_forward", { label });
    },
    async browserReload(label) {
      await invoke("browser_reload", { label });
    },
    async localServers() {
      return (await invoke("local_servers")) as LocalServer[];
    },
    async pickFolder() {
      return (await invoke("pick_folder")) as string | null;
    },
    async spawnPty(id, { cwd, cols, rows }, handlers) {
      const output = listen(`pty://${id}`, (payload) => {
        handlers.onOutput(String(payload));
      });
      const exit = listen(`pty://${id}/exit`, (payload) => {
        output.off();
        exit.off();
        handlers.onExit((payload as { code: number }).code);
      });
      try {
        // Listening first, so no output is missed.
        await Promise.all([output.ready, exit.ready]);
        await invoke("pty_spawn", { id, ...(cwd === null ? {} : { cwd }), cols, rows });
      } catch (error) {
        output.off();
        exit.off();
        throw error instanceof Error ? error : new Error(String(error));
      }
      return {
        write: (data) => void invoke("pty_write", { id, data }),
        resize: (c, r) => void invoke("pty_resize", { id, cols: c, rows: r }),
        kill: () => {
          output.off();
          exit.off();
          void invoke("pty_kill", { id });
        },
      };
    },
    async openExternal(url) {
      await invoke("open_external", { url });
    },
    async openPath(path, reveal) {
      await invoke("open_path", reveal === undefined ? { path } : { path, reveal });
    },
    async openTextFile(path, root) {
      await invoke("open_text_file", { path, root });
    },
    async saveFile(suggestedName, contents) {
      const data = "text" in contents ? { text: contents.text } : { data_base64: contents.base64 };
      return (await invoke("save_file", { suggested_name: suggestedName, ...data })) as
        string | null;
    },
    async notify(title, body, chat, sound) {
      await invoke("notify", {
        title,
        body,
        ...(chat === undefined ? {} : { chat }),
        ...(sound === undefined ? {} : { sound }),
      });
    },
    minimize: () => control("minimize"),
    toggleMaximize: () => control("toggle_maximize"),
    close: () => control("close"),
    startDrag: () => control("start_drag"),
    async showMain() {
      await invoke("show_main");
    },
    async pillUpdate(change) {
      await invoke("pill_update", change);
    },
    async pillPointer() {
      try {
        const at = (await invoke("pill_pointer")) as [number, number] | null;
        return at === null ? null : { x: at[0], y: at[1] };
      } catch {
        return null;
      }
    },
    onTray(event, callback) {
      return listen(`nest://${event}`, callback).off;
    },
    async openInMain(target) {
      await tauri.event.emitTo?.("main", OPEN_EVENT, target);
      await invoke("show_main");
    },
    async windowState() {
      try {
        return (await invoke("window_state")) as { minimized: boolean; visible: boolean };
      } catch {
        return null;
      }
    },
    onWindowMoved(callback) {
      const moved = listen("tauri://move", callback);
      const resized = listen("tauri://resize", callback);
      return () => {
        moved.off();
        resized.off();
      };
    },
    onOpenRequest(callback) {
      return listen(OPEN_EVENT, (payload) => {
        callback(payload as OpenTarget);
      }).off;
    },
    async settings() {
      return fromSaved((await invoke("get_settings")) as SavedSettings);
    },
    async setSettings(change) {
      const args: Record<string, unknown> = {};
      if (change.keepPillOnTop !== undefined) args.keep_pill_on_top = change.keepPillOnTop;
      if (change.startAtLogin !== undefined) args.start_at_login = change.startAtLogin;
      return fromSaved((await invoke("set_settings", args)) as SavedSettings);
    },
  };
}

export const TOKEN_KEY = "nest.desktop.token";
export const DAEMON_KEY = "nest.desktop.daemon";
export const DEFAULT_DAEMON = "http://127.0.0.1:8765";

const LOOPBACK = new Set(["127.0.0.1", "localhost", "[::1]"]);

/** The origin of a daemon on this machine (http or https on a loopback host), else null. */
export function loopbackOrigin(address: string): string | null {
  try {
    const url = new URL(address);
    const web = url.protocol === "http:" || url.protocol === "https:";
    return web && LOOPBACK.has(url.hostname) && url.username === "" && url.password === ""
      ? url.origin
      : null;
  } catch {
    return null;
  }
}

/** Fails every call: a production build opened outside the desktop app talks to no daemon. */
function refusingBridge(): Bridge {
  return {
    ...browserBridge({ search: "" }, null),
    daemon: () => Promise.reject(new Error("This page runs inside the Nest desktop app.")),
  };
}

/**
 * For development in a browser and for tests: the daemon from `?daemon=` (only a loopback
 * address), the token from `?token=`. Both are remembered, the token with the daemon it
 * belongs to, so it never goes to another one. No shell; browser windows open as tabs.
 */
export function browserBridge(
  location: { search: string },
  storage: Storage | null,
  open: (url: string) => void = (url) => {
    window.open(url, "_blank", "noopener,noreferrer");
  },
): Bridge {
  const query = new URLSearchParams(location.search);
  const read = (key: string) => {
    try {
      return storage?.getItem(key) ?? null;
    } catch {
      return null;
    }
  };
  const write = (key: string, value: string | null) => {
    try {
      if (value === null) storage?.removeItem(key);
      else storage?.setItem(key, value);
    } catch {
      // A blocked storage only forgets the daemon for the next start.
    }
  };
  const asked = query.get("daemon");
  const origin = loopbackOrigin(asked ?? read(DAEMON_KEY) ?? DEFAULT_DAEMON);
  let connection: Promise<DaemonConnection>;
  if (origin === null) {
    connection = Promise.reject(new Error(`Not a daemon on this machine: ${asked ?? ""}`));
    // Handled where it is awaited; this keeps it from counting as unhandled meanwhile.
    connection.catch(() => undefined);
  } else {
    write(DAEMON_KEY, origin);
    const saved = (() => {
      try {
        return JSON.parse(read(TOKEN_KEY) ?? "null") as { origin: string; token: string } | null;
      } catch {
        return null;
      }
    })();
    const given = query.get("token");
    let token: string | null = null;
    if (given !== null && given !== "") token = given;
    else if (saved?.origin === origin) token = saved.token;
    write(TOKEN_KEY, token === null ? null : JSON.stringify({ origin, token }));
    connection = Promise.resolve({ base: origin, token });
  }
  let settings: LinuxSettings = { keepPillOnTop: true, startAtLogin: false };
  const nothing = () => Promise.resolve();
  return {
    native: false,
    daemon: () => connection,
    startService: () => Promise.reject(new Error("Start the daemon with nestd serve")),
    openBrowserWindow: (url) => {
      open(url);
      return Promise.resolve(null);
    },
    onBrowserClosed: () => () => undefined,
    browserBack: nothing,
    browserForward: nothing,
    browserReload: nothing,
    localServers: () => Promise.resolve([]),
    pickFolder: () => Promise.resolve(null),
    spawnPty: () => Promise.reject(new Error("Terminals need the desktop app")),
    openExternal: (url) => {
      open(url);
      return Promise.resolve();
    },
    openPath: nothing,
    openTextFile: () => Promise.reject(new Error("Files open in the desktop app")),
    saveFile: () => Promise.resolve(null),
    notify: nothing,
    minimize: nothing,
    toggleMaximize: nothing,
    close: nothing,
    startDrag: nothing,
    showMain: nothing,
    pillUpdate: nothing,
    pillPointer: () => Promise.resolve(null),
    onTray: () => () => undefined,
    openInMain: nothing,
    onOpenRequest: () => () => undefined,
    onWindowMoved: () => () => undefined,
    windowState: () => Promise.resolve(null),
    settings: () => Promise.resolve(settings),
    setSettings: (change) => {
      settings = { ...settings, ...change };
      return Promise.resolve(settings);
    },
  };
}

/**
 * A transcript pane inside the Mac app: the daemon's address and token come from the app
 * when asked, so they stay out of the page's address and globals; no shell or windows.
 */
export function paneBridge(post: PanePost): Bridge {
  const send = async (message: PaneMessage) => {
    await post(message);
  };
  return {
    ...browserBridge({ search: "" }, null),
    native: true,
    pane: post,
    async daemon() {
      const found = (await post({ kind: "daemon" })) as { base: string; token: string };
      return { base: trimmed(found.base), token: found.token };
    },
    openExternal: (url) => send({ kind: "openExternal", url }),
    // The app holds the chat's folder; the page's word for it does not count.
    openTextFile: (path) => send({ kind: "openFile", path }),
    openInMain: (target) => send({ kind: "open", target }),
    async saveFile(suggestedName, contents) {
      if ("base64" in contents) {
        await send({ kind: "saveFile", name: suggestedName, base64: contents.base64 });
      }
      return null;
    },
  };
}

/**
 * The Tauri bridge inside the desktop app. Outside it, the browser stub only in a dev build
 * or a test: the daemon serves the production build too, and a link to that page must not
 * send a token anywhere.
 */
export function platformBridge(
  build: { dev: boolean; mode: string } = { dev: import.meta.env.DEV, mode: import.meta.env.MODE },
): Bridge {
  const tauri = window.__TAURI__;
  if (tauri !== undefined) return tauriBridge(tauri);
  const pane = window.webkit?.messageHandlers?.nestPane;
  if (pane !== undefined) {
    return paneBridge((message) => pane.postMessage(message));
  }
  if (!build.dev && build.mode !== "test") return refusingBridge();
  const storage = (() => {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  })();
  return browserBridge(window.location, storage);
}
