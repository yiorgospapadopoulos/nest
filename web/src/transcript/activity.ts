/**
 * How the chat words what the agent did (D045): durations, thinking and turn lines, and the
 * one-line summary of a group of tool calls.
 */

const SECOND = 1000;

/** "12s", "1m 12s", "1h 2m": a stopwatch reading of `ms`. */
export function elapsed(ms: number): string {
  const seconds = Math.max(0, Math.floor(ms / SECOND));
  if (seconds < 60) return `${String(seconds)}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${String(minutes)}m ${String(seconds % 60)}s`;
  return `${String(Math.floor(minutes / 60))}h ${String(minutes % 60)}m`;
}

/** A finished span reads at least a second, never "0s". */
const finished = (ms: number) => elapsed(Math.max(ms, SECOND));

export function thoughtLabel(ms: number | null): string {
  return ms === null ? "Thought" : `Thought for ${finished(ms)}`;
}

export function turnLabel(ms: number, stopped: boolean): string {
  return `${stopped ? "Stopped after" : "Worked for"} ${finished(ms)}`;
}

export type ToolKind = "command" | "read" | "edit" | "search" | "fetch" | "agent" | "other";

const KINDS: Record<string, ToolKind> = {
  Bash: "command",
  Read: "read",
  Edit: "edit",
  Write: "edit",
  MultiEdit: "edit",
  NotebookEdit: "edit",
  Grep: "search",
  Glob: "search",
  WebFetch: "fetch",
  WebSearch: "fetch",
  Task: "agent",
  Agent: "agent",
};

export function toolKind(name: string): ToolKind {
  return KINDS[name] ?? "other";
}

// Present verb, past verb, one, many.
const WORDS: Record<Exclude<ToolKind, "other">, [string, string, string, string]> = {
  command: ["running", "ran", "command", "commands"],
  read: ["reading", "read", "file", "files"],
  edit: ["editing", "edited", "file", "files"],
  search: ["searching", "searched", "pattern", "patterns"],
  fetch: ["fetching", "fetched", "page", "pages"],
  agent: ["running", "ran", "agent", "agents"],
};

export interface SummarizedTool {
  id: string;
  name: string;
  // Null until the call returns.
  result: string | null;
  failed: boolean;
}

export interface ToolSummary {
  text: string;
  // Any call still running, including background tasks it started.
  running: boolean;
  failed: number;
}

/**
 * "Running 2 commands, reading 1 file" while any call runs, "Ran 3 commands, read 2 files"
 * once all are done. `background` holds the ids of calls whose background task still runs.
 */
export function summarizeTools(
  tools: SummarizedTool[],
  background: ReadonlySet<string>,
): ToolSummary {
  const isRunning = (t: SummarizedTool) => t.result === null || background.has(t.id);
  const running = tools.some(isRunning);
  // Each kind (or other tool's name) with its calls, in the order they first ran.
  const groups = new Map<string, SummarizedTool[]>();
  for (const t of tools) {
    const kind = toolKind(t.name);
    const label = kind === "other" ? `tool:${t.name}` : kind;
    groups.set(label, [...(groups.get(label) ?? []), t]);
  }
  const parts = [...groups].map(([label, calls]) => {
    const n = calls.length;
    if (label.startsWith("tool:")) {
      const times = n > 1 ? ` ${String(n)} times` : "";
      return `${running ? "using" : "used"} ${label.slice(5)}${times}`;
    }
    const [now, past, one, many] = WORDS[label as keyof typeof WORDS];
    const phrase = `${running ? now : past} ${String(n)} ${n === 1 ? one : many}`;
    const done = calls.filter((t) => !isRunning(t)).length;
    return label === "agent" && running && done > 0 ? `${phrase}, ${String(done)} done` : phrase;
  });
  const text = parts.join(", ");
  return {
    text: text.charAt(0).toUpperCase() + text.slice(1),
    running,
    failed: tools.filter((t) => t.failed).length,
  };
}
