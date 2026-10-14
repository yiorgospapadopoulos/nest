import type {
  AccountInfo,
  AgentDefaults,
  Approval,
  ApproveBody,
  Attachment,
  ClaudeChat,
  CommandList,
  Connector,
  CreatePixieBody,
  CreateSessionBody,
  HarnessEvent,
  MergeBody,
  ModelList,
  MonthUsage,
  NotificationSettings,
  Pixie,
  PixieFile,
  PixieSearchHit,
  PushReport,
  PushSubscriptionBody,
  RedeemResponse,
  RepoConfig,
  RepoPatch,
  ResolveBody,
  RewindPreview,
  SearchResults,
  SendResponse,
  Session,
  SessionDetail,
  SessionDiff,
  UpdatePixieBody,
  UpdateSessionBody,
  UsageLimits,
} from "./types.ts";

// The daemon's code for a message refused because Claude Code has the chat open.
export const OPEN_ELSEWHERE = "open_in_claude_code";

const pixiePath = (id: string) => `/api/pixies/${encodeURIComponent(id)}`;

export class ApiError extends Error {
  readonly status: number;
  // A machine-readable reason some refusals carry next to the message.
  readonly code: string | null;
  // The whole JSON body, for refusals that carry more than a message and a code.
  readonly data: Record<string, unknown>;

  constructor(
    status: number,
    message: string,
    code: string | null = null,
    data: Record<string, unknown> = {},
  ) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }

  get unauthorized(): boolean {
    return this.status === 401;
  }
}

export interface Api {
  redeem(code: string, deviceName: string): Promise<RedeemResponse>;
  repos(): Promise<RepoConfig[]>;
  // Unregisters the project (its folder stays); `purge` deletes its chats first.
  removeRepo(name: string, purge: boolean): Promise<null>;
  updateRepo(name: string, patch: RepoPatch): Promise<RepoConfig>;
  sessions(archived: boolean): Promise<Session[]>;
  session(id: string): Promise<SessionDetail>;
  sessionEvents(id: string): Promise<HarnessEvent[]>;
  createSession(body: CreateSessionBody): Promise<Session>;
  // While a turn runs the message is queued (`queued_message`) instead of refused; with
  // `interrupt` the turn is stopped and the message starts right after it.
  sendMessage(
    id: string,
    text: string,
    attachmentIds: string[],
    interrupt?: boolean,
  ): Promise<SendResponse>;
  interrupt(id: string): Promise<null>;
  cancelQueued(id: string, queuedId: string): Promise<null>;
  sessionCommands(id: string): Promise<CommandList>;
  repoCommands(name: string): Promise<CommandList>;
  files(id: string, query: string): Promise<{ files: string[] }>;
  updateSession(id: string, body: UpdateSessionBody): Promise<Session>;
  deleteSession(id: string): Promise<null>;
  search(query: string): Promise<SearchResults>;
  claudeChats(includeAutomated?: boolean): Promise<ClaudeChat[]>;
  claudeChatEvents(id: string): Promise<HarnessEvent[]>;
  adoptClaudeChat(id: string): Promise<Session>;
  setClaudeChatArchived(id: string, archived: boolean): Promise<ClaudeChat>;
  approvals(): Promise<Approval[]>;
  resolveApproval(id: string, body: ResolveBody): Promise<Approval>;
  diff(sessionId: string): Promise<SessionDiff>;
  approve(sessionId: string, body: ApproveBody): Promise<Session>;
  reject(sessionId: string): Promise<Session>;
  feedback(sessionId: string, text: string): Promise<Session>;
  // The daemon reads the failing checks' logs with its own GitHub login and sends them in.
  ciFeedback(sessionId: string): Promise<unknown>;
  rewindPreview(sessionId: string, eventId: number): Promise<RewindPreview>;
  // Restores files (not the conversation) to before the user message `eventId`.
  rewind(sessionId: string, eventId: number): Promise<unknown>;
  // Merges the pull request, then closes the session and removes its worktree.
  merge(sessionId: string, body: MergeBody): Promise<Session>;
  uploadAttachment(file: File): Promise<Attachment>;
  connectors(): Promise<Connector[]>;
  usageMonth(year: number, month: number): Promise<MonthUsage>;
  usageLimits(): Promise<UsageLimits>;
  refreshUsage(): Promise<UsageLimits>;
  reportVisibility(visible: boolean): Promise<null>;
  vapidKey(): Promise<{ public_key: string }>;
  subscribePush(subscription: PushSubscriptionBody): Promise<null>;
  unsubscribePush(endpoint: string): Promise<null>;
  testPush(): Promise<PushReport>;
  notificationSettings(): Promise<NotificationSettings>;
  saveNotificationSettings(settings: NotificationSettings): Promise<NotificationSettings>;
  models(): Promise<ModelList>;
  account(): Promise<AccountInfo>;
  agentDefaults(): Promise<AgentDefaults>;
  saveAgentDefaults(defaults: AgentDefaults): Promise<AgentDefaults>;
  pixies(): Promise<Pixie[]>;
  createPixie(body: CreatePixieBody): Promise<Pixie>;
  updatePixie(id: string, body: UpdatePixieBody): Promise<Pixie>;
  deletePixie(id: string): Promise<null>;
  sendToPixie(id: string, text: string): Promise<Session>;
  resetPixie(id: string): Promise<Pixie>;
  pixieFile(id: string, name: string): Promise<PixieFile>;
  savePixieFile(id: string, name: string, text: string, hash: string | null): Promise<PixieFile>;
  pixieNotes(id: string): Promise<string[]>;
  searchPixie(id: string, q: string): Promise<PixieSearchHit[]>;
}

// Search results asked for at once; the daemon allows up to 100.
export const SEARCH_LIMIT = 50;

const session = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;
const repo = (name: string) => `/api/repos/${encodeURIComponent(name)}`;
const claudeChat = (id: string) => `/api/claude-chats/${encodeURIComponent(id)}`;

/** The daemon's REST API; the device token travels in the same-origin cookie. */
export class HttpApi implements Api {
  private readonly fetchFn: typeof fetch;

  constructor(fetchFn: typeof fetch = (input, init) => fetch(input, init)) {
    this.fetchFn = fetchFn;
  }

  redeem(code: string, deviceName: string) {
    return this.json<RedeemResponse>("POST", "/api/pairing/redeem", {
      code,
      device_name: deviceName,
    });
  }

  repos() {
    return this.json<RepoConfig[]>("GET", "/api/repos");
  }

  removeRepo(name: string, purge: boolean) {
    return this.json<null>("DELETE", `${repo(name)}?purge_sessions=${String(purge)}`);
  }

  updateRepo(name: string, patch: RepoPatch) {
    return this.json<RepoConfig>("PATCH", repo(name), patch);
  }

  sessions(archived: boolean) {
    return this.json<Session[]>("GET", `/api/sessions?archived=${String(archived)}`);
  }

  session(id: string) {
    return this.json<SessionDetail>("GET", session(id));
  }

  sessionEvents(id: string) {
    return this.json<HarnessEvent[]>("GET", `${session(id)}/events`);
  }

  createSession(body: CreateSessionBody) {
    return this.json<Session>("POST", "/api/sessions", body);
  }

  sendMessage(id: string, text: string, attachmentIds: string[], interrupt = false) {
    return this.json<SendResponse>("POST", `${session(id)}/messages`, {
      text,
      attachment_ids: attachmentIds,
      ...(interrupt ? { interrupt: true } : {}),
    });
  }

  interrupt(id: string) {
    return this.json<null>("POST", `${session(id)}/interrupt`);
  }

  cancelQueued(id: string, queuedId: string) {
    return this.json<null>("DELETE", `${session(id)}/queue/${encodeURIComponent(queuedId)}`);
  }

  sessionCommands(id: string) {
    return this.json<CommandList>("GET", `${session(id)}/commands`);
  }

  /** The repo's last known commands, for a new chat that has no session yet. */
  repoCommands(name: string) {
    return this.json<CommandList>("GET", `${repo(name)}/commands`);
  }

  /** Up to 50 repo files ranked by the daemon for an @ mention. */
  files(id: string, query: string) {
    return this.json<{ files: string[] }>(
      "GET",
      `${session(id)}/files?q=${encodeURIComponent(query)}`,
    );
  }

  updateSession(id: string, body: UpdateSessionBody) {
    return this.json<Session>("PATCH", session(id), body);
  }

  deleteSession(id: string) {
    return this.json<null>("DELETE", `${session(id)}?purge=true`);
  }

  /** Chat titles and messages across projects, best match first. */
  search(query: string) {
    return this.json<SearchResults>(
      "GET",
      `/api/search?q=${encodeURIComponent(query)}&limit=${String(SEARCH_LIMIT)}`,
    );
  }

  claudeChats(includeAutomated = false) {
    const query = includeAutomated ? "?include_automated=true" : "";
    return this.json<ClaudeChat[]>("GET", `/api/claude-chats${query}`);
  }

  claudeChatEvents(id: string) {
    return this.json<HarnessEvent[]>("GET", `${claudeChat(id)}/events`);
  }

  adoptClaudeChat(id: string) {
    return this.json<Session>("POST", `${claudeChat(id)}/adopt`);
  }

  setClaudeChatArchived(id: string, archived: boolean) {
    return this.json<ClaudeChat>("PUT", `${claudeChat(id)}/archived`, { archived });
  }

  approvals() {
    return this.json<Approval[]>("GET", "/api/approvals?status=pending");
  }

  resolveApproval(id: string, body: ResolveBody) {
    return this.json<Approval>("POST", `/api/approvals/${encodeURIComponent(id)}/resolve`, body);
  }

  diff(sessionId: string) {
    return this.json<SessionDiff>("GET", `${session(sessionId)}/diff`);
  }

  approve(sessionId: string, body: ApproveBody) {
    return this.json<Session>("POST", `${session(sessionId)}/approve`, body);
  }

  reject(sessionId: string) {
    return this.json<Session>("POST", `${session(sessionId)}/reject`);
  }

  feedback(sessionId: string, text: string) {
    return this.json<Session>("POST", `${session(sessionId)}/feedback`, { text });
  }

  ciFeedback(sessionId: string) {
    return this.json<unknown>("POST", `${session(sessionId)}/ci-feedback`);
  }

  rewindPreview(sessionId: string, eventId: number) {
    return this.json<RewindPreview>(
      "GET",
      `${session(sessionId)}/rewind?message=${String(eventId)}`,
    );
  }

  rewind(sessionId: string, eventId: number) {
    return this.json<unknown>("POST", `${session(sessionId)}/rewind`, { message: eventId });
  }

  merge(sessionId: string, body: MergeBody) {
    return this.json<Session>("POST", `${session(sessionId)}/merge`, body);
  }

  uploadAttachment(file: File) {
    const form = new FormData();
    form.append("file", file);
    return this.send<Attachment>("/api/attachments", { method: "POST", body: form });
  }

  connectors() {
    return this.json<Connector[]>("GET", "/api/connectors");
  }

  usageMonth(year: number, month: number) {
    return this.json<MonthUsage>(
      "GET",
      `/api/usage/month?year=${String(year)}&month=${String(month)}`,
    );
  }

  usageLimits() {
    return this.json<UsageLimits>("GET", "/api/usage/limits");
  }

  /** Asks Claude for fresh limits now; 429 within 20 s of the last refresh. */
  refreshUsage() {
    return this.json<UsageLimits>("POST", "/api/usage/refresh");
  }

  reportVisibility(visible: boolean) {
    return this.json<null>("POST", "/api/clients/visibility", { visible, client: "pwa" });
  }

  vapidKey() {
    return this.json<{ public_key: string }>("GET", "/api/push/vapid-key");
  }

  subscribePush(subscription: PushSubscriptionBody) {
    return this.json<null>("POST", "/api/push/subscribe", subscription);
  }

  unsubscribePush(endpoint: string) {
    return this.json<null>("DELETE", "/api/push/subscribe", { endpoint });
  }

  testPush() {
    return this.json<PushReport>("POST", "/api/push/test");
  }

  notificationSettings() {
    return this.json<NotificationSettings>("GET", "/api/notifications/settings");
  }

  saveNotificationSettings(settings: NotificationSettings) {
    return this.json<NotificationSettings>("PUT", "/api/notifications/settings", settings);
  }

  models() {
    return this.json<ModelList>("GET", "/api/models");
  }

  account() {
    return this.json<AccountInfo>("GET", "/api/account");
  }

  agentDefaults() {
    return this.json<AgentDefaults>("GET", "/api/agents/defaults");
  }

  /** 422 when the model does not take the chosen thinking level. */
  saveAgentDefaults(defaults: AgentDefaults) {
    return this.json<AgentDefaults>("PUT", "/api/agents/defaults", defaults);
  }

  pixies() {
    return this.json<Pixie[]>("GET", "/api/pixies");
  }

  createPixie(body: CreatePixieBody) {
    return this.json<Pixie>("POST", "/api/pixies", body);
  }

  updatePixie(id: string, body: UpdatePixieBody) {
    return this.json<Pixie>("PATCH", pixiePath(id), body);
  }

  deletePixie(id: string) {
    return this.json<null>("DELETE", pixiePath(id));
  }

  sendToPixie(id: string, text: string) {
    return this.json<Session>("POST", `${pixiePath(id)}/messages`, { text });
  }

  resetPixie(id: string) {
    return this.json<Pixie>("POST", `${pixiePath(id)}/reset`);
  }

  // `name` is soul, memory or notes/<name>; the slash is part of the path.
  pixieFile(id: string, name: string) {
    return this.json<PixieFile>("GET", `${pixiePath(id)}/files/${name}`);
  }

  /** 409 `stale_file` when `hash` is not the current one. */
  savePixieFile(id: string, name: string, text: string, hash: string | null) {
    return this.json<PixieFile>("PUT", `${pixiePath(id)}/files/${name}`, { text, hash });
  }

  pixieNotes(id: string) {
    return this.json<string[]>("GET", `${pixiePath(id)}/notes`);
  }

  searchPixie(id: string, q: string) {
    return this.json<PixieSearchHit[]>("GET", `${pixiePath(id)}/search?q=${encodeURIComponent(q)}`);
  }

  private json<T>(method: string, path: string, body?: unknown): Promise<T> {
    const init: RequestInit = { method };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
      init.headers = { "Content-Type": "application/json" };
    }
    return this.send<T>(path, init);
  }

  private async send<T>(path: string, init: RequestInit): Promise<T> {
    const response = await this.fetchFn(path, { ...init, credentials: "same-origin" });
    const text = await response.text();
    const data: unknown = text ? parse(text) : null;
    if (!response.ok) {
      throw new ApiError(
        response.status,
        field(data, "detail") ?? `Request failed (${String(response.status)})`,
        field(data, "code"),
        isRecord(data) ? data : {},
      );
    }
    return data as T;
  }
}

function parse(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isRecord(data: unknown): data is Record<string, unknown> {
  return typeof data === "object" && data !== null && !Array.isArray(data);
}

function field(data: unknown, name: "detail" | "code"): string | null {
  const value = isRecord(data) ? data[name] : undefined;
  return typeof value === "string" ? value : null;
}
