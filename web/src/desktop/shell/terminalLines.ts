// Lines Run in terminal types into terminal panes, by pane id. A pane that is only now
// opening takes its lines once its view is up and its shell has started.
import type { LineSource } from "./terminalSession.ts";

type Typer = (line: string) => void;

const waiting = new Map<string, string[]>();
const typers = new Map<string, Typer>();

/** Types `line` into the terminal pane `pane`, now or as soon as it is up. */
export function typeLine(pane: string, line: string): void {
  const typer = typers.get(pane);
  if (typer !== undefined) {
    typer(line);
    return;
  }
  waiting.set(pane, [...(waiting.get(pane) ?? []), line]);
}

/** The lines of terminal pane `pane`, for its session (connectTerminal). */
export function linesFor(pane: string, dropped: (count: number) => void): LineSource {
  return {
    attach(type) {
      typers.set(pane, type);
      const lines = waiting.get(pane) ?? [];
      waiting.delete(pane);
      for (const line of lines) type(line);
      return () => {
        if (typers.get(pane) === type) typers.delete(pane);
      };
    },
    dropped,
  };
}
