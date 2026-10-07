import { list, obj, str, toolArg } from "../api/payloads.ts";
import type { Approval, HarnessEvent, JsonObject } from "../api/types.ts";
import { permissionOf } from "../api/payloads.ts";

export type TranscriptItem =
  | { kind: "user"; key: string; text: string; attachments: string[] }
  | { kind: "assistant"; key: string; text: string }
  | {
      kind: "tool";
      key: string;
      name: string;
      arg: string;
      result: string | null;
      detail: string | null;
      failed: boolean;
    }
  | { kind: "approval"; key: string; approval: Approval }
  | { kind: "system"; key: string; text: string };

type ToolItem = Extract<TranscriptItem, { kind: "tool" }>;

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
  for (const e of events) {
    const key = String(e.id);
    const p = e.payload;
    switch (e.type) {
      case "session.user_message":
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
      default:
        note(items, key, systemText(e));
    }
  }
  return items;
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
    } else if (block.type === "tool_use") {
      const tool: ToolItem = {
        kind: "tool",
        key: blockKey,
        name: str(block.name) ?? "Tool",
        arg: toolArg(obj(block.input), root),
        result: null,
        detail: null,
        failed: false,
      };
      tools.set(str(block.id) ?? blockKey, tool);
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
    case "session.state":
      if (p.state === "interrupted") return "Interrupted";
      if (p.state === "failed") return failure(str(p.error));
      return null;
    case "session.result":
      return p.is_error === true ? "The turn ended with an error" : null;
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
