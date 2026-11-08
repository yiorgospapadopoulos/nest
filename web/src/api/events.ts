import type { NestEvent } from "./types.ts";

// The daemon's close codes (daemon/src/nestd/api/routes/events.py).
export const UNAUTHENTICATED = 4401;
export const FORBIDDEN_ORIGIN = 4403;

// Global events settings screens reload on (daemon/src/nestd/events/types.py). Every engine
// account after any change (B98), with `GET /api/accounts`'s body (`accountsOf` reads it).
export const ACCOUNTS_CHANGED = "accounts.changed";
// Local models were added or removed, or their engine changed (B106); `{}`, so clients
// fetch `GET /api/local/models` again.
export const LOCAL_MODELS_CHANGED = "local_models.changed";
// Claude Code reported another list of models, as after its first sign in (B136); `{}`, so
// clients fetch `GET /api/models` again.
export const ENGINE_MODELS = "engine.models";
// The engine updates' state, with `GET /api/updates`'s body. Not stored, so clients read it
// again on every connect.
export const UPDATES_CHANGED = "updates.changed";

export interface SocketLike {
  onopen: (() => void) | null;
  onmessage: ((message: { data: unknown }) => void) | null;
  onclose: ((close: { code: number }) => void) | null;
  close(): void;
}

export type SocketFactory = (url: string) => SocketLike;

/**
 * The subprotocols that carry a device token to the event socket (B117), since a browser
 * socket cannot send headers: the daemon answers with "nest" and reads the token from the
 * second. Only for a daemon at another origin; the phone app's cookie needs none.
 */
export function tokenProtocols(token: string): string[] {
  return ["nest", `nest.token.${token}`];
}

/** Browser sockets that send `token` as a subprotocol, or none without one. */
export function browserSockets(token: string | null): SocketFactory {
  return (url) =>
    (token === null
      ? new WebSocket(url)
      : new WebSocket(url, tokenProtocols(token))) as unknown as SocketLike;
}

export interface StreamHandlers {
  onEvent(event: NestEvent): void;
  // `resumed` is false when events may have been missed, so snapshots should be reloaded.
  onOpen(resumed: boolean): void;
  // The socket closed and a reconnect is on its way.
  onLost(): void;
  onClosed(reason: "unauthorized" | "forbidden"): void;
}

export interface Timers {
  set(callback: () => void, ms: number): number;
  clear(id: number): void;
}

const browserTimers: Timers = {
  set: (callback, ms) => window.setTimeout(callback, ms),
  clear: (id) => {
    window.clearTimeout(id);
  },
};

export const BASE_DELAY_MS = 1000;
export const MAX_DELAY_MS = 30000;

export function eventsUrl(location: { protocol: string; host: string }, after: number | null) {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const query = after === null ? "" : `?after=${String(after)}`;
  return `${scheme}://${location.host}/api/events${query}`;
}

/**
 * The live event socket. Stored events move the cursor, so a reconnect replays what was
 * missed with `after`; ephemeral events (id null) never do. Reconnects back off up to
 * MAX_DELAY_MS, or come at once on `wake`, and stop for good when the daemon rejects the
 * device or the origin.
 */
export class EventStream {
  private socket: SocketLike | null = null;
  private timer: number | null = null;
  private attempts = 0;
  private readonly connect: SocketFactory;
  private readonly urlFor: (after: number | null) => string;
  private readonly handlers: StreamHandlers;
  private readonly timers: Timers;
  cursor: number | null = null;

  constructor(
    connect: SocketFactory,
    urlFor: (after: number | null) => string,
    handlers: StreamHandlers,
    timers: Timers = browserTimers,
  ) {
    this.connect = connect;
    this.urlFor = urlFor;
    this.handlers = handlers;
    this.timers = timers;
  }

  start(): void {
    this.open();
  }

  /** Reconnects now if a reconnect is waiting, as when the phone wakes or goes online. */
  wake(): void {
    if (this.timer === null) return;
    this.timers.clear(this.timer);
    this.timer = null;
    this.attempts = 0;
    this.open();
  }

  stop(): void {
    if (this.timer !== null) {
      this.timers.clear(this.timer);
      this.timer = null;
    }
    const socket = this.socket;
    this.socket = null;
    socket?.close();
  }

  private open(): void {
    const resumed = this.cursor !== null;
    const socket = this.connect(this.urlFor(this.cursor));
    this.socket = socket;
    socket.onopen = () => {
      this.attempts = 0;
      this.handlers.onOpen(resumed);
    };
    socket.onmessage = (message) => {
      this.receive(message.data);
    };
    socket.onclose = (close) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.closed(close.code);
    };
  }

  private receive(data: unknown): void {
    if (typeof data !== "string") return;
    let event: NestEvent;
    try {
      event = JSON.parse(data) as NestEvent;
    } catch {
      return;
    }
    if (event.id !== null) {
      this.cursor = Math.max(this.cursor ?? 0, event.id);
    }
    this.handlers.onEvent(event);
  }

  private closed(code: number): void {
    if (code === UNAUTHENTICATED || code === FORBIDDEN_ORIGIN) {
      this.handlers.onClosed(code === UNAUTHENTICATED ? "unauthorized" : "forbidden");
      return;
    }
    this.handlers.onLost();
    const delay = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** this.attempts);
    this.attempts += 1;
    this.timer = this.timers.set(() => {
      this.timer = null;
      this.open();
    }, delay);
  }
}
