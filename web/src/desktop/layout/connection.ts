// Reaching the daemon again, ported from NestKit's Backoff (EventStream.swift), DaemonText
// and ServiceStarter: the banner's line and buttons, the service's start, and the retries.

import type { Updating } from "../bridge.ts";

/** The delay in seconds before retry `attempt` (1 for the first): 0.5, doubled, at most 30. */
export function backoffDelay(attempt: number): number {
  return Math.min(30, 0.5 * 2 ** Math.max(0, attempt - 1));
}

export type Connection =
  | { kind: "connecting" }
  | { kind: "connected" }
  // The last try failed; the next comes after `delay` seconds.
  | { kind: "reconnecting"; attempt: number; delay: number };

/** The banner's line; null while connected or connecting. */
export function bannerText(connection: Connection): string | null {
  if (connection.kind !== "reconnecting") return null;
  return connection.attempt > 1
    ? `Can't reach the Nest daemon. Trying again in ${String(Math.ceil(connection.delay))}s`
    : "Reconnecting to the Nest daemon";
}

export type ServiceState =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "started" }
  // No user unit to start: the service was never installed. Holds the install command.
  | { kind: "notInstalled"; command: string }
  | { kind: "failed"; reason: string };

/**
 * The command that installs the user service, run in the Nest checkout, as the Mac's
 * DaemonService.installCommand: nestd is not on the PATH, uv runs it from there. Without
 * the checkout's path, a placeholder says where to run it.
 */
export function installCommand(checkout: string | null): string {
  const daemon =
    checkout === null
      ? "<your Nest checkout>/daemon"
      : `'${`${checkout.replace(/\/+$/, "")}/daemon`.replaceAll("'", "'\\''")}'`;
  return `cd ${daemon} && uv run nestd service install`;
}

export const DEFAULT_RELEASE_URL =
  "https://github.com/yiorgospapadopoulos/nest/releases/latest/download";
// The latest release's install.sh on the project's GitHub Pages, for a short line (B162).
export const INSTALL_SCRIPT_URL = "https://yiorgospapadopoulos.github.io/nest/install.sh";

/**
 * What repairs an install and keeps the data (release/install.sh), from the address the
 * install came from, as the daemon's install_line: a piped script cannot tell it otherwise.
 */
export function installLine(releaseUrl: string): string {
  const url = releaseUrl.replace(/\/+$/, "");
  return url === DEFAULT_RELEASE_URL
    ? `curl -fsSL ${INSTALL_SCRIPT_URL} | sh`
    : `curl -fsSL ${url}/install.sh | NEST_RELEASE_URL=${url} sh`;
}

// An update's note older than this is left over, not an update under way.
const UPDATE_FRESH_MS = 5 * 60_000;
// After this an update says it is taking longer than usual; most take a few seconds.
const UPDATE_SLOW_MS = 15_000;

/** When it started, in ms; the daemon writes microseconds, which not every engine reads. */
function startedAt(text: string): number {
  return Date.parse(text.replace(/(\.\d{3})\d+/, "$1"));
}

/** Whether `update.json` says an update is under way: there, and not left over. */
function underWay(updating: Updating, now: number): boolean {
  const started = startedAt(updating.started_at);
  return !Number.isNaN(started) && now - started < UPDATE_FRESH_MS;
}

// How long the Updating screen waits for the daemon once `update.json` no longer says so:
// going back, the watcher clears it and only then starts the old version (B130, fix 30b).
const AFTER_UPDATE_MS = 30_000;

/** The update the Updating screen shows, and when `update.json` stopped saying so. */
export interface UpdateHold {
  updating: Updating;
  ended: number | null;
}

/**
 * What shows instead of the daemon-down screen while the daemon is down for an update
 * (B130), after a read of `update.json`: the update under way, or for
 * `AFTER_UPDATE_MS` the last one, so the screen stays until the daemon answers rather than
 * giving way to the window and the app's own start of the service mid-rollback.
 */
export function holdUpdate(
  hold: UpdateHold | null,
  updating: Updating | null,
  now: number,
): UpdateHold | null {
  if (updating !== null && underWay(updating, now)) return { updating, ended: null };
  if (hold === null) return null;
  const ended = hold.ended ?? now;
  return now - ended < AFTER_UPDATE_MS ? { updating: hold.updating, ended } : null;
}

/** What the Updating screen shows: the version it goes to, and whether it is slow. */
export function heldView(
  hold: UpdateHold | null,
  now: number,
): { version: string; slow: boolean } | null {
  if (hold === null) return null;
  const started = startedAt(hold.updating.started_at);
  return { version: hold.updating.to_version, slow: now - started >= UPDATE_SLOW_MS };
}

/** After a second failed try, so a daemon just starting shows no alarm. */
export function daemonDown(connection: Connection): boolean {
  return connection.kind === "reconnecting" && connection.attempt > 1;
}

export type BannerAction = "retry" | "startService";

/** Retry (not while the service starts) and Start Nest service while it cannot be reached. */
export function bannerActions(connection: Connection, service: ServiceState): BannerAction[] {
  const starting = service.kind === "starting";
  const offersStart = connection.kind === "reconnecting" && !starting;
  return [
    ...(starting ? [] : ["retry" as const]),
    ...(offersStart ? ["startService" as const] : []),
  ];
}

/** Starts the service through the platform; the state to show after. */
export async function startService(
  start: () => Promise<"started" | "not_installed">,
  checkout: string | null = null,
): Promise<ServiceState> {
  try {
    return (await start()) === "started"
      ? { kind: "started" }
      : { kind: "notInstalled", command: installCommand(checkout) };
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error);
    return { kind: "failed", reason: reason === "" ? "The service did not start" : reason };
  }
}

export interface Timers {
  set(callback: () => void, ms: number): number;
  clear(id: number): void;
}

/**
 * Tries `attempt` until it succeeds, waiting the backoff's delay after each failure, and
 * reports each change. `retry` tries again at once, from the first delay, as the Mac's
 * connect() does. With `after` failures already behind it, it starts by waiting, so a
 * daemon that answers but then fails again is not asked over and over.
 */
export class RetryLoop {
  private attempts = 0;
  private timer: number | null = null;
  private trying = false;
  private stopped = false;
  private again = false;
  private readonly attempt: () => Promise<boolean>;
  private readonly report: (connection: Connection) => void;
  private readonly timers: Timers;

  constructor(
    attempt: () => Promise<boolean>,
    report: (connection: Connection) => void,
    timers: Timers,
    after = 0,
  ) {
    this.attempt = attempt;
    this.report = report;
    this.timers = timers;
    this.attempts = after;
  }

  /** How many tries failed in a row. */
  get failures(): number {
    return this.attempts;
  }

  start(): void {
    if (this.attempts === 0) void this.run();
    else this.wait();
  }

  retry(): void {
    if (this.stopped) return;
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
    this.attempts = 0;
    if (this.trying) this.again = true;
    else void this.run();
  }

  private isStopped(): boolean {
    return this.stopped;
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) this.timers.clear(this.timer);
    this.timer = null;
  }

  private async tried(): Promise<boolean> {
    try {
      return await this.attempt();
    } catch {
      return false;
    }
  }

  private async run(): Promise<void> {
    if (this.stopped) return;
    this.trying = true;
    const reached = await this.tried();
    this.trying = false;
    // Stopped while it tried: nothing more is reported.
    if (this.isStopped()) return;
    if (reached) {
      this.attempts = 0;
      this.report({ kind: "connected" });
      return;
    }
    if (this.again) {
      this.again = false;
      void this.run();
      return;
    }
    this.attempts += 1;
    this.wait();
  }

  private wait(): void {
    const delay = backoffDelay(this.attempts);
    this.report({ kind: "reconnecting", attempt: this.attempts, delay });
    this.timer = this.timers.set(() => {
      this.timer = null;
      void this.run();
    }, delay * 1000);
  }
}
