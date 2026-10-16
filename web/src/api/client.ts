import type {
  AccountInfo,
  AgentDefaults,
  AgentWork,
  CallWork,
  Goal,
  GroupEntry,
  SendAwayBody,
  Approval,
  ApproveBody,
  Attachment,
  ClaudeChat,
  CommandList,
  Connector,
  CreatePixieBody,
  CreateTeamBody,
  CreateSessionBody,
  Habit,
  HabitBody,
  HabitRun,
  Health,
  NestEvent,
  MergeBody,
  ModelList,
  MonthUsage,
  NotificationSettings,
  Pixie,
  PixieActivity,
  PixieFile,
  PixieReport,
  PixieSearchHit,
  PixieTeam,
  PushReport,
  PushSubscriptionBody,
  RedeemResponse,
  RepoConfig,
  RepoPatch,
  ResolveBody,
  ForkReply,
  MemoryReply,
  MemoryScope,
  Restore,
  RewindPreview,
  RewindReply,
  ShellResult,
  SearchResults,
  SendResponse,
  Session,
  SessionDetail,
  SessionDiff,
  UpdateHabitBody,
  UpdatePixieBody,
  UpdateSessionBody,
  UpdateTeamBody,
  UsageLimits,
} from "./types.ts";

// The daemon's code for a message refused because Claude Code has the chat open.
export const OPEN_ELSEWHERE = "open_in_claude_code";

const pixiePath = (id: string) => `/api/pixies/${encodeURIComponent(id)}`;
const teamPath = (id: string) => `/api/pixie-teams/${encodeURIComponent(id)}`;
const habitPath = (pixie: string, id: string) =>
  `${pixiePath(pixie)}/habits/${encodeURIComponent(id)}`;

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
  repo(name: string): Promise<RepoConfig>;
  // Unregisters the project (its folder stays); `purge` deletes its chats first.
  removeRepo(name: string, purge: boolean): Promise<null>;
  updateRepo(name: string, patch: RepoPatch): Promise<RepoConfig>;
  sessions(archived: boolean): Promise<Session[]>;
  session(id: string): Promise<SessionDetail>;
  sessionEvents(id: string): Promise<NestEvent[]>;
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
  // Stops one background task or subagent, by its task id or the tool use id that started it.
  stopTask(id: string, taskId: string): Promise<null>;
  // Takes back a message Claude has not read; 409 `message_taken` once it has.
  cancelQueued(id: string, queuedId: string): Promise<null>;
  // Stops the turn if one runs and starts this pending message next.
  sendNow(id: string, queuedId: string): Promise<null>;
  sessionCommands(id: string): Promise<CommandList>;
  repoCommands(name: string): Promise<CommandList>;
  files(id: string, query: string): Promise<{ files: string[] }>;
  updateSession(id: string, body: UpdateSessionBody): Promise<Session>;
  deleteSession(id: string): Promise<null>;
  search(query: string): Promise<SearchResults>;
  claudeChats(includeAutomated?: boolean): Promise<ClaudeChat[]>;
  claudeChatEvents(id: string): Promise<NestEvent[]>;
  adoptClaudeChat(id: string): Promise<Session>;
  setClaudeChatArchived(id: string, archived: boolean): Promise<ClaudeChat>;
  approvals(): Promise<Approval[]>;
  resolveApproval(id: string, body: ResolveBody): Promise<Approval>;
  diff(sessionId: string): Promise<SessionDiff>;
  approve(sessionId: string, body: ApproveBody): Promise<Session>;
  feedback(sessionId: string, text: string): Promise<Session>;
  // The daemon reads the failing checks' logs with its own GitHub login and sends them in.
  ciFeedback(sessionId: string): Promise<unknown>;
  rewindPreview(sessionId: string, eventId: number, restore?: Restore): Promise<RewindPreview>;
  // Restores the files, the conversation or both to before the user message `eventId`.
  rewind(sessionId: string, eventId: number, restore?: Restore): Promise<RewindReply>;
  // A new chat with the conversation before the user message `eventId`.
  fork(sessionId: string, eventId: number): Promise<ForkReply>;
  // Runs a `!` command in the chat's folder; 200 even when the command fails.
  shell(sessionId: string, command: string): Promise<ShellResult>;
  // Appends a `#` memory to the project's or the user's CLAUDE.md.
  remember(sessionId: string, text: string, scope: MemoryScope): Promise<MemoryReply>;
  // A stored file, such as an image in a tool result, as data.
  attachment(id: string): Promise<Blob>;
  // Merges the pull request, then closes the session and removes its worktree.
  merge(sessionId: string, body: MergeBody): Promise<Session>;
  uploadAttachment(file: File): Promise<Attachment>;
  connectors(): Promise<Connector[]>;
  usageMonth(year: number, month: number): Promise<MonthUsage>;
  usageLimits(): Promise<UsageLimits>;
  refreshUsage(): Promise<UsageLimits>;
  // 202 at once; the daemon then exits and launchd starts it again.
  restartService(): Promise<{ restarting: boolean }>;
  health(): Promise<Health>;
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
  reorderPixies(ids: string[]): Promise<Pixie[]>;
  sendToPixie(id: string, text: string): Promise<Session>;
  resetPixie(id: string): Promise<Pixie>;
  pixieFile(id: string, name: string): Promise<PixieFile>;
  savePixieFile(id: string, name: string, text: string, hash: string | null): Promise<PixieFile>;
  pixieNotes(id: string): Promise<string[]>;
  pixieActivity(id: string): Promise<PixieActivity[]>;
  searchPixie(id: string, q: string): Promise<PixieSearchHit[]>;
  duplicatePixie(id: string): Promise<Pixie>;
  teams(): Promise<PixieTeam[]>;
  createTeam(body: CreateTeamBody): Promise<PixieTeam>;
  updateTeam(id: string, body: UpdateTeamBody): Promise<PixieTeam>;
  deleteTeam(id: string): Promise<null>;
  habits(pixieId: string): Promise<Habit[]>;
  createHabit(pixieId: string, body: HabitBody): Promise<Habit>;
  updateHabit(pixieId: string, id: string, body: UpdateHabitBody): Promise<Habit>;
  deleteHabit(pixieId: string, id: string): Promise<null>;
  // Queues a run at once, whatever the usage; 202 with the run.
  runHabit(pixieId: string, id: string): Promise<HabitRun>;
  habitRuns(pixieId: string, id: string): Promise<HabitRun[]>;
  // Newest first, the latest 200; `unread` only those not read yet.
  pixieReports(unread: boolean): Promise<PixieReport[]>;
  readReport(id: string): Promise<unknown>;
  // Marks every report of the pixie read.
  readPixieReports(pixieId: string): Promise<unknown>;
  // Every chat's pixies and teams, by session id, for chats that have any (B46).
  pixieGroups(): Promise<Record<string, GroupEntry[]>>;
  // The project's chats that are working or have steps showing, with their steps (D092).
  goals(repo: string): Promise<Goal[]>;
  // The pixie, or the team with its members, leaves the chat's group; returns the group.
  sendAway(sessionId: string, body: SendAwayBody): Promise<GroupEntry[]>;
  // Every call to the pixie in the chat, newest first, with its work.
  pixieCalls(sessionId: string, pixieId: string): Promise<CallWork[]>;
  // A subagent's transcript so far; 404 for a call the chat did not make.
  agentTranscript(sessionId: string, toolUseId: string): Promise<AgentWork>;
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

  repo(name: string) {
    return this.json<RepoConfig>("GET", repo(name));
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
    return this.json<NestEvent[]>("GET", `${session(id)}/events`);
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

  stopTask(id: string, taskId: string) {
    return this.json<null>("POST", `${session(id)}/tasks/${encodeURIComponent(taskId)}/stop`);
  }

  cancelQueued(id: string, queuedId: string) {
    return this.json<null>("DELETE", `${session(id)}/queue/${encodeURIComponent(queuedId)}`);
  }

  sendNow(id: string, queuedId: string) {
    return this.json<null>("POST", `${session(id)}/queue/${encodeURIComponent(queuedId)}/send-now`);
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
    return this.json<NestEvent[]>("GET", `${claudeChat(id)}/events`);
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

  feedback(sessionId: string, text: string) {
    return this.json<Session>("POST", `${session(sessionId)}/feedback`, { text });
  }

  ciFeedback(sessionId: string) {
    return this.json<unknown>("POST", `${session(sessionId)}/ci-feedback`);
  }

  rewindPreview(sessionId: string, eventId: number, restore: Restore = "code") {
    return this.json<RewindPreview>(
      "GET",
      `${session(sessionId)}/rewind?message=${String(eventId)}&restore=${restore}`,
    );
  }

  rewind(sessionId: string, eventId: number, restore: Restore = "code") {
    return this.json<RewindReply>("POST", `${session(sessionId)}/rewind`, {
      message: eventId,
      restore,
    });
  }

  fork(sessionId: string, eventId: number) {
    return this.json<ForkReply>("POST", `${session(sessionId)}/fork`, { message: eventId });
  }

  shell(sessionId: string, command: string) {
    return this.json<ShellResult>("POST", `${session(sessionId)}/shell`, { command });
  }

  remember(sessionId: string, text: string, scope: MemoryScope) {
    return this.json<MemoryReply>("POST", `${session(sessionId)}/memory`, { text, scope });
  }

  async attachment(id: string) {
    const path = `/api/attachments/${encodeURIComponent(id)}`;
    const response = await this.fetchFn(path, { credentials: "same-origin" });
    if (!response.ok) throw failure(response.status, parse(await response.text()));
    return response.blob();
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

  restartService() {
    return this.json<{ restarting: boolean }>("POST", "/api/service/restart");
  }

  health() {
    return this.json<Health>("GET", "/api/health");
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

  /** `ids` names every pixie once, in the new order; 422 otherwise (D072). */
  reorderPixies(ids: string[]) {
    return this.json<Pixie[]>("PUT", "/api/pixies/order", { ids });
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

  /** What the pixie did in chats, newest first; the latest 200 are kept (B41). */
  pixieActivity(id: string) {
    return this.json<PixieActivity[]>("GET", `${pixiePath(id)}/activity`);
  }

  searchPixie(id: string, q: string) {
    return this.json<PixieSearchHit[]>("GET", `${pixiePath(id)}/search?q=${encodeURIComponent(q)}`);
  }

  /** A copy right under the original, in its team, named "<name> 2" (B40). */
  duplicatePixie(id: string) {
    return this.json<Pixie>("POST", `${pixiePath(id)}/duplicate`);
  }

  teams() {
    return this.json<PixieTeam[]>("GET", "/api/pixie-teams");
  }

  createTeam(body: CreateTeamBody) {
    return this.json<PixieTeam>("POST", "/api/pixie-teams", body);
  }

  updateTeam(id: string, body: UpdateTeamBody) {
    return this.json<PixieTeam>("PATCH", teamPath(id), body);
  }

  /** Its pixies stay, without a team. */
  deleteTeam(id: string) {
    return this.json<null>("DELETE", teamPath(id));
  }

  /** Ordered by when they were created (B42). */
  habits(pixieId: string) {
    return this.json<Habit[]>("GET", `${pixiePath(pixieId)}/habits`);
  }

  createHabit(pixieId: string, body: HabitBody) {
    return this.json<Habit>("POST", `${pixiePath(pixieId)}/habits`, body);
  }

  updateHabit(pixieId: string, id: string, body: UpdateHabitBody) {
    return this.json<Habit>("PATCH", habitPath(pixieId, id), body);
  }

  /** Its queued runs are cancelled. */
  deleteHabit(pixieId: string, id: string) {
    return this.json<null>("DELETE", habitPath(pixieId, id));
  }

  runHabit(pixieId: string, id: string) {
    return this.json<HabitRun>("POST", `${habitPath(pixieId, id)}/run`);
  }

  /** The latest 20 ended runs, newest first, and any queued or running. */
  habitRuns(pixieId: string, id: string) {
    return this.json<HabitRun[]>("GET", `${habitPath(pixieId, id)}/runs`);
  }

  pixieReports(unread: boolean) {
    return this.json<PixieReport[]>("GET", `/api/pixie-reports?unread=${String(unread)}`);
  }

  readReport(id: string) {
    return this.json<unknown>("POST", `/api/pixie-reports/${encodeURIComponent(id)}/read`);
  }

  readPixieReports(pixieId: string) {
    return this.json<unknown>("POST", `${pixiePath(pixieId)}/reports/read`);
  }

  pixieGroups() {
    return this.json<Record<string, GroupEntry[]>>("GET", "/api/pixie-groups");
  }

  goals(repo: string) {
    return this.json<Goal[]>("GET", `/api/goals?repo=${encodeURIComponent(repo)}`);
  }

  sendAway(sessionId: string, body: SendAwayBody) {
    return this.json<GroupEntry[]>("POST", `${session(sessionId)}/pixies/send-away`, body);
  }

  pixieCalls(sessionId: string, pixieId: string) {
    return this.json<CallWork[]>(
      "GET",
      `${session(sessionId)}/pixies/${encodeURIComponent(pixieId)}/calls`,
    );
  }

  agentTranscript(sessionId: string, toolUseId: string) {
    return this.json<AgentWork>(
      "GET",
      `${session(sessionId)}/agents/${encodeURIComponent(toolUseId)}/transcript`,
    );
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
    if (!response.ok) throw failure(response.status, data);
    return data as T;
  }
}

/** The error of a refused request, with the daemon's detail and code when it gave them. */
function failure(status: number, data: unknown): ApiError {
  return new ApiError(
    status,
    field(data, "detail") ?? `Request failed (${String(status)})`,
    field(data, "code"),
    isRecord(data) ? data : {},
  );
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
