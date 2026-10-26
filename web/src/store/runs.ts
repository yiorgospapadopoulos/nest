import { obj, str } from "../api/payloads.ts";
import type { JsonObject, RunStatus } from "../api/types.ts";
import type { State } from "./state.ts";

// The daemon keeps this many lines of a run's output; the sheet keeps no more.
export const OUTPUT_LINES = 2000;

/**
 * A chat's run status (B108), given to every chat known in the same folder too: they share
 * one run. With no id, only the chats already in that folder take it, as from an event.
 */
export function withRunStatus(state: State, status: RunStatus, id?: string): State {
  const runs = { ...state.runs };
  for (const [key, known] of Object.entries(runs)) {
    if (status.folder !== null && known.folder === status.folder) runs[key] = status;
  }
  if (id !== undefined) runs[id] = status;
  return { ...state, runs };
}

/** `run.changed`: the folder's run started, stopped, exited or its ports changed. */
export function runChanged(state: State, p: JsonObject): State {
  const status = obj(p.status);
  return str(status.state) === null ? state : withRunStatus(state, status as unknown as RunStatus);
}

/** `run.output`: a chunk of output, kept only for a folder whose output is open. */
export function runOutputAdded(state: State, p: JsonObject): State {
  const folder = str(p.folder) ?? "";
  const known = state.runOutput[folder];
  return known === undefined ? state : withRunOutput(state, folder, known + (str(p.text) ?? ""));
}

export function withRunOutput(state: State, folder: string, text: string): State {
  return { ...state, runOutput: { ...state.runOutput, [folder]: lastLines(text) } };
}

/** The text's last OUTPUT_LINES lines, with a line still being written as the last. */
export function lastLines(text: string): string {
  const lines = text.split("\n");
  return lines.length > OUTPUT_LINES + 1 ? lines.slice(-OUTPUT_LINES - 1).join("\n") : text;
}
