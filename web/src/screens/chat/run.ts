import type { RunStatus } from "../../api/types.ts";

/** The listening ports as the header shows them: up to three, else the first two and "+N". */
export function portsText(ports: number[]): string {
  const shown = ports.length > 3 ? ports.slice(0, 2) : ports;
  const more = ports.length - shown.length;
  return shown.join(", ") + (more > 0 ? ` +${String(more)}` : "");
}

/** Whether the run's process is alive, so it can be stopped. */
export function isAlive(status: RunStatus): boolean {
  return status.state === "starting" || status.state === "running";
}

/** The exit code of a run that ended on its own with an error, else null. */
export function failedCode(status: RunStatus): number | null {
  return status.state === "exited" && status.exit_code !== 0 ? status.exit_code : null;
}
