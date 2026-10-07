import type {
  Approval,
  ContextUsage,
  JsonObject,
  JsonValue,
  PrStatus,
  QueuedAttachment,
  QueuedMessage,
  StuckFlag,
  StuckReason,
} from "./types.ts";

// Approval payloads and tool inputs are free-form JSON; these read them defensively.

export function str(value: JsonValue | undefined): string | null {
  return typeof value === "string" ? value : null;
}

export function num(value: JsonValue | undefined): number {
  return typeof value === "number" ? value : 0;
}

export function obj(value: JsonValue | undefined): JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : {};
}

export function list(value: JsonValue | undefined): JsonValue[] {
  return Array.isArray(value) ? value : [];
}

// The input field that best describes a tool call, as the daemon's activity lines pick it.
const ARG_KEYS = ["command", "file_path", "notebook_path", "pattern", "path", "url", "query"];
const EXTRA_KEYS = ["subject", "description", "taskId", "prompt"];

/** A one-line description of a tool call; paths inside `root` are shown relative to it. */
export function toolArg(input: JsonObject, root: string | null): string {
  for (const key of [...ARG_KEYS, ...EXTRA_KEYS]) {
    const value = input[key];
    if ((typeof value === "string" && value !== "") || typeof value === "number") {
      return relative(String(value), root).replace(/\n[\s\S]*$/, "");
    }
  }
  return "";
}

function relative(value: string, root: string | null): string {
  if (root === null) return value;
  const prefix = root.endsWith("/") ? root : `${root}/`;
  return value.startsWith(prefix) ? value.slice(prefix.length) : value;
}

export interface PermissionView {
  tool: string;
  // The Bash command, or the tool with its main argument.
  command: string;
  why: string | null;
}

export function permissionOf(approval: Approval, root: string | null): PermissionView {
  const tool = str(approval.payload.tool) ?? "Tool";
  const input = obj(approval.payload.input);
  const command =
    tool === "Bash" ? (str(input.command) ?? "") : `${tool} ${toolArg(input, root)}`.trim();
  return { tool, command, why: str(input.description) ?? str(approval.payload.title) };
}

export interface QuestionOption {
  label: string;
  description: string | null;
  recommended: boolean;
}

export interface QuestionView {
  question: string;
  header: string | null;
  multiSelect: boolean;
  options: QuestionOption[];
}

export function questionsOf(approval: Approval): QuestionView[] {
  return list(approval.payload.questions).map((value) => {
    const q = obj(value);
    return {
      question: str(q.question) ?? "",
      header: str(q.header),
      multiSelect: q.multi_select === true,
      options: list(q.options).map((option) => {
        const o = obj(option);
        return {
          label: str(o.label) ?? "",
          description: str(o.description),
          recommended: o.recommended === true,
        };
      }),
    };
  });
}

export interface ReviewView {
  files: number;
  additions: number;
  deletions: number;
  paths: string[];
  summary: string | null;
}

export function reviewOf(approval: Approval): ReviewView {
  const p = approval.payload;
  return {
    files: num(p.files),
    additions: num(p.additions),
    deletions: num(p.deletions),
    paths: list(p.paths).filter((path): path is string => typeof path === "string"),
    summary: str(p.summary),
  };
}

/** The plan's markdown, as Claude wrote it for ExitPlanMode. */
export function planOf(approval: Approval): string {
  return str(approval.payload.plan) ?? "";
}

/** A session's context window use, or null when it is unknown or malformed. */
export function contextOf(value: JsonValue | undefined): ContextUsage | null {
  const c = obj(value);
  const { percent, used, limit } = c;
  if (typeof percent !== "number" || typeof used !== "number" || typeof limit !== "number") {
    return null;
  }
  return { percent, used, limit };
}

/** A `session.pr` event's status, or null when it is malformed. */
export function prOf(value: JsonValue | undefined): PrStatus | null {
  const p = obj(value);
  const checks = obj(p.checks);
  if (typeof p.number !== "number" || typeof p.state !== "string" || !Array.isArray(checks.items)) {
    return null;
  }
  return p as unknown as PrStatus;
}

export interface MergeView {
  number: number;
  title: string;
  url: string;
  passed: number;
}

export function mergeOf(approval: Approval): MergeView {
  const p = approval.payload;
  return {
    number: num(p.number),
    title: str(p.title) ?? approval.title,
    url: str(p.url) ?? "",
    passed: num(obj(p.checks).passed),
  };
}

/** The queued messages of a `session.queued` event, oldest first. */
export function queuedOf(value: JsonValue | undefined): QueuedMessage[] {
  return list(value).flatMap((value) => {
    const q = obj(value);
    const { id, text } = q;
    if (typeof id !== "string" || typeof text !== "string") return [];
    const attachments = list(q.attachments).map(obj) as unknown as QueuedAttachment[];
    return [{ id, text, attachments, created_at: str(q.created_at) ?? "" }];
  });
}

const STUCK_REASONS: readonly string[] = ["waiting", "silent", "repeating", "long_turn"];

/** A `session.stuck` payload, or null when it is not one. */
export function stuckOf(value: JsonObject): StuckFlag | null {
  const reason = str(value.reason);
  const since = str(value.since);
  if (reason === null || !STUCK_REASONS.includes(reason) || since === null) return null;
  return { reason: reason as StuckReason, since, details: str(value.details) ?? "" };
}
