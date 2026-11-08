import { ApiError } from "./client.ts";
import type {
  Approval,
  ArtifactStorageChange,
  ContextUsage,
  EngineAccount,
  EngineUpdates,
  JsonObject,
  JsonValue,
  LocalApp,
  LocalModelNotLoaded,
  LocalServerDown,
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

/**
 * A permission's tool call on one line, after its tool's name. Nest's own worktree tool
 * reads as `worktree remove <folder name>`.
 */
export function toolCall(tool: string, input: JsonObject, root: string | null): string {
  if (tool !== "worktree") return `${tool} ${toolArg(input, root)}`.trim();
  const path = str(input.worktree);
  const folder = path === null ? "" : (path.replace(/\/+$/, "").split("/").pop() ?? "");
  return [tool, str(input.action) ?? "", folder].filter((part) => part !== "").join(" ");
}

export interface PermissionView {
  tool: string;
  // The Bash command, or the tool with its main argument.
  command: string;
  why: string | null;
  // Why it asks, when it says: Claude Code's reason, or what a worktree to remove still
  // holds, one item per line.
  reason: string | null;
  // What "Always allow" allows from now on: Claude Code's suggested rule, else the tool.
  always: string;
  // False when the daemon offers no "Always allow", such as removing a worktree with work.
  canAlways: boolean;
}

export function permissionOf(approval: Approval, root: string | null): PermissionView {
  const tool = str(approval.payload.tool) ?? "Tool";
  const input = obj(approval.payload.input);
  const command = tool === "Bash" ? (str(input.command) ?? "") : toolCall(tool, input, root);
  return {
    tool,
    command,
    why: str(input.description) ?? str(approval.payload.title),
    reason: str(approval.payload.reason),
    always: str(approval.payload.always_rule) ?? tool,
    canAlways: approval.payload.always !== false,
  };
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

export interface RestackView {
  branch: string | null;
  base: string;
  rebased: boolean;
  error: string | null;
  // The chat's open pull request; null when it has none.
  number: number | null;
  url: string | null;
}

/** A `restack` approval: a stacked chat's branch that has to move onto `base` (B149). */
export function restackOf(approval: Approval): RestackView {
  const p = approval.payload;
  return {
    branch: str(p.branch),
    base: str(p.base) ?? "",
    rebased: p.rebased === true,
    error: str(p.error),
    number: typeof p.number === "number" ? p.number : null,
    url: str(p.url),
  };
}

export interface ReviewCommentView {
  id: string;
  path: string | null;
  line: number | null;
  outdated: boolean;
  body: string;
}

export interface ReviewCommentsView {
  number: number;
  url: string;
  changesRequested: boolean;
  comments: ReviewCommentView[];
}

export function reviewCommentsOf(approval: Approval): ReviewCommentsView {
  const p = approval.payload;
  return {
    number: num(p.number),
    url: str(p.url) ?? "",
    changesRequested: p.changes_requested === true,
    comments: list(p.comments).map((value, i) => {
      const c = obj(value);
      return {
        id: str(c.id) ?? String(i),
        path: str(c.path),
        line: typeof c.line === "number" ? c.line : null,
        outdated: c.outdated === true,
        body: str(c.body) ?? "",
      };
    }),
  };
}

/** The Needs you detail of review comments, as NestKit's NeedsYouLine words it. */
export function reviewCommentsDetail(approval: Approval): string {
  const { number, comments, changesRequested } = reviewCommentsOf(approval);
  const detail = `${String(comments.length)} on #${String(number)}`;
  return changesRequested ? `${detail}, changes requested` : detail;
}

/**
 * Where a comment is, as NestKit's ReviewComment.location: "src/a.ts:12",
 * "src/a.ts (outdated, was line 12)" or "General review comment"; `short` keeps the file's name.
 */
export function commentPlace(comment: ReviewCommentView, short = false): string {
  if (comment.path === null) return "General review comment";
  const file = short ? comment.path.slice(comment.path.lastIndexOf("/") + 1) : comment.path;
  if (comment.line === null) return file;
  const line = String(comment.line);
  return comment.outdated ? `${file} (outdated, was line ${line})` : `${file}:${line}`;
}

/** The pending messages of a `session.queued` event, oldest first. */
export function queuedOf(value: JsonValue | undefined): QueuedMessage[] {
  return list(value).flatMap((value) => {
    const q = obj(value);
    const { id, text } = q;
    if (typeof id !== "string" || typeof text !== "string") return [];
    const attachments = list(q.attachments).map(obj) as unknown as QueuedAttachment[];
    return [{ id, text, attachments, created_at: str(q.created_at) ?? "", sent: q.sent === true }];
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

/** An `artifact.storage` event's change, its fields read plainly; null without an artifact. */
export function storageChangeOf(p: JsonObject): ArtifactStorageChange | null {
  const id = str(p.artifact_id);
  if (id === null) return null;
  const set = Object.fromEntries(
    Object.entries(obj(p.set)).filter((entry): entry is [string, string] => {
      return typeof entry[1] === "string";
    }),
  );
  const remove = list(p.remove).filter((key): key is string => typeof key === "string");
  return { artifact_id: id, set, remove, clear: p.clear === true };
}

/** The pixie call an approval was raised in (B114), by tool use id. */
export interface PixieCallRef {
  // The caller chat's group slot: a team member's is its leader's call.
  call: string;
  // The innermost call, the member's own.
  agent: string;
}

/** Where an approval came from inside a pixie call, or null outside one (B114). */
export function pixieCallOf(approval: Approval): PixieCallRef | null {
  const call = str(approval.payload.call);
  const agent = str(approval.payload.agent);
  return call === null || agent === null ? null : { call, agent };
}

/** An `accounts.changed` payload's accounts (B98), or null when it is not one. */
export function accountsOf(p: JsonObject): EngineAccount[] | null {
  return Array.isArray(p.accounts) ? (p.accounts as unknown as EngineAccount[]) : null;
}

/** An `updates.changed` payload, or null when it is not one. */
export function updatesOf(p: JsonObject): EngineUpdates | null {
  return typeof p.state === "string" && Array.isArray(p.engines)
    ? (p as unknown as EngineUpdates)
    : null;
}

// A chat's model `local:<id>` runs that local model (B106).
export const LOCAL_MODEL_PREFIX = "local:";

export function localModelValue(id: string): string {
  return `${LOCAL_MODEL_PREFIX}${id}`;
}

export function isLocalModel(model: string | null): boolean {
  return model?.startsWith(LOCAL_MODEL_PREFIX) === true;
}

export const LOCAL_SERVER_DOWN = "local_server_down";
export const LOCAL_MODEL_NOT_LOADED = "local_model_not_loaded";
const LOCAL_APPS: readonly string[] = ["lmstudio", "ollama"] satisfies LocalApp[];

function text(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function serverDown(p: Record<string, unknown>): LocalServerDown {
  const start = text(p.start);
  return {
    code: LOCAL_SERVER_DOWN,
    app: text(p.app),
    address: text(p.address),
    start: start !== null && LOCAL_APPS.includes(start) ? (start as LocalApp) : null,
  };
}

/**
 * Why a local chat's turn failed, from the top of its `session.state` payload (D129): its
 * server went away, or LM Studio could not load the model. Null for anything else.
 */
export function localFailureOf(p: JsonObject): LocalServerDown | LocalModelNotLoaded | null {
  if (p.code === LOCAL_SERVER_DOWN) return serverDown(p);
  if (p.code !== LOCAL_MODEL_NOT_LOADED) return null;
  return {
    code: LOCAL_MODEL_NOT_LOADED,
    detail: text(p.detail) ?? "",
    app: text(p.app),
    address: text(p.address),
    model: text(p.model),
  };
}

/**
 * The server a refused create, send or add names: a 409 `local_server_down`, whose message
 * was not taken. Null for any other error.
 */
export function serverDownOf(error: unknown): LocalServerDown | null {
  if (!(error instanceof ApiError) || error.status !== 409) return null;
  return error.code === LOCAL_SERVER_DOWN ? serverDown(error.data) : null;
}
