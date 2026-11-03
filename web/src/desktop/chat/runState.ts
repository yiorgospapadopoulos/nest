// The Run control at the right of a chat's header (B108), ported from NestKit's
// RunControl.swift: Run, Starting, the port chips and stop, or Exited N.
import type { RunStatus, Session } from "../../api/types.ts";

export interface RunPort {
  port: number;
  // The first port, with its green dot.
  live: boolean;
  // Null for a daemon on another machine: its localhost is not this one.
  url: string | null;
  help: string;
}

export type RunControl =
  | { kind: "run"; help: string }
  | { kind: "starting"; help: string }
  | { kind: "running"; ports: RunPort[]; more: number; moreHelp: string | null; stopHelp: string }
  | { kind: "exited"; label: string; help: string };

// More ports than this show the first two and "+N".
export const MAXIMUM_CHIPS = 3;

/** Every listening port as a chip, the first one live. */
export function runPorts(status: RunStatus, machine: string | null = null): RunPort[] {
  return status.listening.map((port, index) => ({
    port,
    live: index === 0,
    url: machine === null ? `http://localhost:${String(port)}` : null,
    help: portHelp(port, status.block, machine),
  }));
}

function portHelp(port: number, block: RunStatus["block"], machine: string | null): string {
  if (machine !== null) return `Runs on ${machine}`;
  if (block !== null && (port < block.start || port > block.end)) {
    return `Outside this folder's ports ${String(block.start)} to ${String(block.end)}`;
  }
  return `Open localhost:${String(port)}`;
}

/** Null when the chat has no run command, or its status is not read yet. */
export function runControl(
  status: RunStatus | null | undefined,
  compact = false,
  machine: string | null = null,
): RunControl | null {
  if (status?.available !== true || status.command === null) return null;
  const command = status.command;
  const starting = { kind: "starting", help: `Starting ${command}. Click to stop` } as const;
  switch (status.state) {
    case "starting":
      return starting;
    case "running": {
      if (status.listening.length === 0) return starting;
      const ports = runPorts(status, machine);
      const shown = compact ? 1 : ports.length > MAXIMUM_CHIPS ? MAXIMUM_CHIPS - 1 : ports.length;
      const rest = ports.slice(shown).map((p) => String(p.port));
      return {
        kind: "running",
        ports: ports.slice(0, shown),
        more: rest.length,
        moreHelp: rest.length === 0 ? null : `Also ${rest.join(", ")}`,
        stopHelp: `Stop ${command}`,
      };
    }
    case "exited":
      if (status.exit_code === null || status.exit_code === 0) {
        return { kind: "run", help: `Run ${command}` };
      }
      return {
        kind: "exited",
        label: `Exited ${String(status.exit_code)}`,
        help: `${command} exited with code ${String(status.exit_code)}. Click to run again`,
      };
    default:
      return { kind: "run", help: `Run ${command}` };
  }
}

/** The output pane's title: the run's command. */
export function runPaneTitle(status: RunStatus | null | undefined): string {
  return status?.command ?? "Run";
}

/** The output pane's quiet place: the chat's branch, else its project. */
export function runPanePlace(session: Session | undefined): string | null {
  if (session === undefined) return null;
  return session.branch ?? session.repo;
}
