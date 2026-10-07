import { list, obj, str, toolArg } from "../api/payloads.ts";
import type { Approval, HarnessEvent, JsonObject, JsonValue } from "../api/types.ts";
import { permissionOf } from "../api/payloads.ts";
import { turnLabel } from "./activity.ts";

export interface ToolItem {
  kind: "tool";
  key: string;
  // The tool use id, which background tasks are tracked by.
  id: string;
  name: string;
  arg: string;
  result: string | null;
  detail: string | null;
  failed: boolean;
}

export interface ThinkingItem {
  kind: "thinking";
  key: string;
  // Empty when the engine left the thinking out.
  text: string;
  // Null when unknown, as in Claude Code's own transcripts.
  ms: number | null;
}

export type TranscriptItem =
  | { kind: "user"; key: string; text: string; attachments: string[] }
  | { kind: "assistant"; key: string; text: string }
  | ToolItem
  | ThinkingItem
  // Consecutive tool calls (two or more) with the thinking between them (D045).
  | { kind: "tools"; key: string; items: (ToolItem | ThinkingItem)[] }
  | { kind: "approval"; key: string; approval: Approval }
  | { kind: "system"; key: string; text: string }
  // "Worked for 1m 12s" or "Stopped after 40s" at the end of a turn.
  | { kind: "turn"; key: string; text: string };

// States that end a turn; the others continue it or have nothing to do with turns.
const TURN_ENDS = new Set<JsonValue | undefined>(["idle", "interrupted", "failed"]);

const DETAIL_LIMIT = 4000;
// Task list bookkeeping shows in the Goals strip instead.
const HIDDEN_TOOLS = new Set(["TaskCreate", "TaskUpdate", "TaskList", "TaskGet"]);
const SUMMARY_LIMIT = 40;

/**
 * The chat transcript from its stored events. Subagent messages are left out (they show
 * in the Agents sheet); approvals still pending render as inline cards, finished ones as
 * a short note.
 */
export function buildTranscript(
  events: HarnessEvent[],
  pending: Record<string, Approval>,
  root: string | null,
): TranscriptItem[] {
  const finals = new Map<string, Approval>();
  for (const e of events) {
    if (e.type === "approval.resolved") {
      const approval = e.payload.approval as unknown as Approval;
      finals.set(approval.id, approval);
    }
  }
  const items: TranscriptItem[] = [];
  const tools = new Map<string, ToolItem>();
  // The open turn's result: a turn a queued message ends has no other end (D045).
  let result: { ms: number | null; key: string } | null = null;
  for (const e of events) {
    const key = String(e.id);
    const p = e.payload;
    switch (e.type) {
      case "session.user_message":
        if (result !== null && result.ms !== null) {
          items.push({ kind: "turn", key: `${result.key}.end`, text: turnLabel(result.ms, false) });
        }
        result = null;
        items.push({
          kind: "user",
          key,
          text: str(p.text) ?? "",
          attachments: list(p.attachments).map((a) => str(obj(a).filename) ?? "file"),
        });
        break;
      case "session.message":
        if (p.parent_tool_use_id === null || p.parent_tool_use_id === undefined) {
          addBlocks(items, tools, list(p.blocks).map(obj), key, root);
        }
        break;
      case "approval.created": {
        const approval = p.approval as unknown as Approval;
        const current = pending[approval.id];
        if (current !== undefined) {
          items.push({ kind: "approval", key, approval: current });
        } else {
          note(items, key, resolvedText(finals.get(approval.id), root));
        }
        break;
      }
      case "session.result":
        result = { ms: num(p.duration_ms), key };
        note(items, key, p.is_error === true ? "The turn ended with an error" : null);
        break;
      case "session.state":
        if (TURN_ENDS.has(p.state)) {
          endTurn(items, key, p, num(p.duration_ms) ?? result?.ms ?? null);
          result = null;
        }
        break;
      default:
        note(items, key, systemText(e));
    }
  }
  return groupTools(items);
}

/** The end of a turn: how long it worked, or ran before it was stopped or failed. */
function endTurn(items: TranscriptItem[], key: string, p: JsonObject, ms: number | null): void {
  if (p.state === "failed") note(items, key, failure(str(p.error)));
  if (ms !== null) {
    items.push({ kind: "turn", key: `${key}.end`, text: turnLabel(ms, p.state !== "idle") });
  } else if (p.state === "interrupted") {
    note(items, key, "Interrupted");
  }
}

/**
 * When the running turn started, for its live timer: its `turn_start` mark, or its user
 * message in history from before the mark existed. Null when no turn runs.
 */
export function turnStart(events: HarnessEvent[]): string | null {
  for (const e of [...events].reverse()) {
    if (e.type === "session.user_message") return e.ts;
    if (e.type !== "session.state") continue;
    if (e.payload.turn_start === true) return e.ts;
    if (TURN_ENDS.has(e.payload.state) || e.payload.state === "closed") return null;
  }
  return null;
}

/** Runs of two or more tool calls become one group; thinking between them joins it. */
function groupTools(items: TranscriptItem[]): TranscriptItem[] {
  const grouped: TranscriptItem[] = [];
  // The run so far, from its first call to its last, and thinking since its last call.
  let run: (ToolItem | ThinkingItem)[] = [];
  let tail: ThinkingItem[] = [];
  let key = "";
  const flush = () => {
    if (run.filter((item) => item.kind === "tool").length > 1) {
      grouped.push({ kind: "tools", key, items: run });
    } else {
      grouped.push(...run);
    }
    grouped.push(...tail);
    run = [];
    tail = [];
  };
  for (const item of items) {
    if (item.kind === "tool") {
      if (run.length === 0) key = item.key;
      run = [...run, ...tail, item];
      tail = [];
    } else if (item.kind === "thinking" && run.length > 0) {
      tail.push(item);
    } else {
      flush();
      grouped.push(item);
    }
  }
  flush();
  return grouped;
}

function num(value: JsonValue | undefined): number | null {
  return typeof value === "number" ? value : null;
}

function addBlocks(
  items: TranscriptItem[],
  tools: Map<string, ToolItem>,
  blocks: JsonObject[],
  key: string,
  root: string | null,
): void {
  blocks.forEach((block, index) => {
    const blockKey = `${key}.${String(index)}`;
    if (block.type === "text") {
      const text = str(block.text) ?? "";
      if (text.trim()) items.push({ kind: "assistant", key: blockKey, text });
    } else if (block.type === "thinking") {
      items.push({
        kind: "thinking",
        key: blockKey,
        text: str(block.text) ?? "",
        ms: num(block.duration_ms),
      });
    } else if (block.type === "tool_use") {
      const tool: ToolItem = {
        kind: "tool",
        key: blockKey,
        id: str(block.id) ?? blockKey,
        name: str(block.name) ?? "Tool",
        arg: toolArg(obj(block.input), root),
        result: null,
        detail: null,
        failed: false,
      };
      tools.set(tool.id, tool);
      if (!HIDDEN_TOOLS.has(tool.name)) items.push(tool);
    } else if (block.type === "tool_result") {
      const tool = tools.get(str(block.tool_use_id) ?? "");
      if (tool !== undefined) {
        const content = str(block.content) ?? "";
        tool.failed = block.is_error === true;
        tool.result = resultSummary(content, tool.failed);
        tool.detail = content.trim() ? content.slice(0, DETAIL_LIMIT) : null;
      }
    }
  });
}

export function resultSummary(content: string, failed: boolean): string {
  if (failed) return "failed";
  const lines = content.split("\n").filter((line) => line.trim());
  const first = lines[0]?.trim() ?? "";
  if (lines.length > 1) return `${String(lines.length)} lines`;
  if (!first) return "done";
  return first.length > SUMMARY_LIMIT ? `${first.slice(0, SUMMARY_LIMIT - 1)}…` : first;
}

function note(items: TranscriptItem[], key: string, text: string | null): void {
  if (text !== null) items.push({ kind: "system", key, text });
}

function resolvedText(approval: Approval | undefined, root: string | null): string | null {
  if (approval === undefined || approval.status === "superseded") return null;
  if (approval.status === "expired") return "Request expired";
  const r = approval.resolution ?? {};
  switch (approval.kind) {
    case "permission": {
      const command = permissionOf(approval, root).command;
      return r.behavior === "allow" ? `Allowed: ${command}` : `Rejected: ${command}`;
    }
    case "question":
      return r.dismissed === true
        ? "Question dismissed"
        : `Answered: ${Object.values(obj(r.answers)).map(String).join("; ")}`;
    case "plan": {
      if (r.decision === "approve") return "Plan approved";
      const message = str(r.message);
      return message === null ? "Keep planning" : `Keep planning: ${message}`;
    }
    case "review":
      if (r.action === "rejected") return "Rejected. Nothing merged";
      return str(r.pr_url) === null ? "Approved and committed" : "Approved. Pull request opened";
    case "merge":
      // A merge shows as the "Pull request merged" line of its own event.
      return r.dismissed === true ? "Merge dismissed" : null;
  }
}

function failure(error: string | null): string {
  return error === null ? "Failed" : `Failed: ${error}`;
}

function systemText(e: HarnessEvent): string | null {
  const p = e.payload;
  switch (e.type) {
    case "session.setup_failed":
      return `Setup failed: ${str(p.command) ?? ""}`;
    case "session.git_violation":
      return "The agent changed git refs itself";
    case "git.failed":
      return `Git ${str(p.step) ?? ""} failed`;
    case "pr.opened":
      return "Pull request opened";
    case "pr.merged":
      return `Pull request merged (${str(p.method) ?? "squash"})`;
    default:
      return null;
  }
}
