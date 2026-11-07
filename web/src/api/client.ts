import type {
  AccountInfo,
  AccountList,
  AccountProvider,
  AccountSignIn,
  AddedLocalModels,
  BankedResets,
  BankedResetUsed,
  CheckResult,
  EngineAccount,
  EngineUpdates,
  SetupCheck,
  SetupReport,
  SetupState,
  FoundModels,
  IssueList,
  IssueShow,
  LocalApp,
  LocalEngine,
  LocalModelList,
  LocalUsage,
  AgentDefaults,
  CodexAccount,
  CodexMarketplace,
  CodexPlugins,
  ConfigurationPage,
  CopyPreview,
  CopyResult,
  EngineId,
  EngineLimits,
  FeaturesCatalog,
  FileText,
  McpServer,
  ProjectConfiguration,
  ProviderList,
  SharedItem,
  AgentWork,
  BranchMap,
  Artifact,
  ArtifactAnswer,
  AskStatus,
  ArtifactContent,
  ArtifactDetail,
  ArtifactFilter,
  ArtifactStorage,
  ArtifactStorageWrite,
  ArtifactVersion,
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
  RemotesRefresh,
  RepoPatch,
  ResolveBody,
  ForkReply,
  MemoryReply,
  MemoryScope,
  Restore,
  RewindPreview,
  RewindReply,
  RunOutput,
  RunStatus,
  RunVerb,
  ShellResult,
  SearchResults,
  SelectPlaceBody,
  SendResponse,
  Session,
  SetAutopilot,
  SessionDetail,
  SessionDiff,
  UpdateHabitBody,
  UpdatePixieBody,
  UpdateSessionBody,
  UpdateTeamBody,
  UsageLimits,
  UsagePeriod,
  PeriodUnit,
  AvailablePlugin,
  InstalledPlugin,
  Marketplace,
  PluginDetails,
  PixieSkill,
  ClaudeAccount,
  ListedDevice,
  GithubAccount,
  PairingCode,
  LimitSettings,
  PixieDefaults,
  StorageSettings,
  PerfView,
  StorageUsage,
  StoredAttachment,
  StuckSettings,
  UsageSettings,
} from "./types.ts";

// The apps a project's folder opens in (daemon/src/nestd/local_apps/openers.py): VS Code, the
// file manager ("finder" on every platform) and a terminal.
export type RepoApp = "vscode" | "finder" | "terminal";

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
  // Registers a folder as a project, named after the folder unless `name` is given.
  registerRepo(path: string, name?: string): Promise<RepoConfig>;
  // Unregisters the project (its folder stays); `purge` deletes its chats first.
  removeRepo(name: string, purge: boolean): Promise<null>;
  updateRepo(name: string, patch: RepoPatch): Promise<RepoConfig>;
  // Saves the project order every client shows (D090); announced as `repos.reordered`.
  reorderRepos(order: string[]): Promise<RepoConfig[]>;
  // Opens the project's folder in an app on the daemon's machine, as the Mac's project menu.
  openRepo(name: string, app: RepoApp): Promise<null>;
  // Gitignored files in the project's checkout worth linking into its worktrees.
  linkSuggestions(name: string): Promise<string[]>;
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
  // Opens the chat in Claude Code in a terminal on the daemon's machine; `warning` is set
  // when Nest runs the chat too.
  openInClaudeCode(id: string): Promise<{ launcher: string; warning: string | null }>;
  // Stops one background task or subagent, by its task id or the tool use id that started it.
  stopTask(id: string, taskId: string): Promise<null>;
  // Takes back a message Claude has not read; 409 `message_taken` once it has.
  cancelQueued(id: string, queuedId: string): Promise<null>;
  // Stops the turn if one runs and starts this pending message next.
  sendNow(id: string, queuedId: string): Promise<null>;
  // Ends a usage limit pause now (B78): the queued messages, else a continue message, go.
  resumeLimit(id: string): Promise<Session>;
  setAutopilot(id: string, body: SetAutopilot): Promise<Session>;
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
  // Reads the chat's pull request from GitHub now.
  refreshPr(sessionId: string): Promise<Session>;
  // Sends the pull request's waiting review comments to the agent and marks them sent
  // (B101): those of `ids`, or all without; 409 `no_review_comments` when none waits.
  reviewFeedback(sessionId: string, ids?: string[]): Promise<SendResponse>;
  // Whether new review comments go to the agent as they arrive (B101).
  setReviewAutoSend(sessionId: string, autoSend: boolean): Promise<Session>;
  // The project's open GitHub issues (B101); without `show`, as the project's setting says.
  // 502 when GitHub cannot be read.
  issues(repo: string, show?: IssueShow, refresh?: boolean): Promise<IssueList>;
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
  attachmentThere(id: string): Promise<void>;
  // The dev server of the chat's folder (B108); start and restart answer 409 when the chat
  // has no run command.
  run(sessionId: string): Promise<RunStatus>;
  runControl(sessionId: string, verb: RunVerb): Promise<RunStatus>;
  runOutput(sessionId: string): Promise<RunOutput>;
  // Merges the pull request, then closes the session and removes its worktree.
  merge(sessionId: string, body: MergeBody): Promise<Session>;
  uploadAttachment(file: File): Promise<Attachment>;
  connectors(): Promise<Connector[]>;
  usagePeriod(unit: PeriodUnit, date: string): Promise<UsagePeriod>;
  usageLimits(): Promise<UsageLimits>;
  refreshUsage(): Promise<UsageLimits>;
  // Another engine's windows (B91); refreshing is refused with 429 within 20 s.
  engineLimits(provider: string): Promise<EngineLimits>;
  refreshEngineUsage(provider: string): Promise<EngineLimits>;
  // 202 at once; the daemon then exits and launchd starts it again.
  restartService(): Promise<{ restarting: boolean }>;
  updates(): Promise<EngineUpdates>;
  // Starts a check unless one runs, and answers with the state so far.
  checkUpdates(): Promise<EngineUpdates>;
  // Both 202 at once, then the daemon exits as for a restart; 409 with nothing to do.
  relaunchUpdate(): Promise<{ restarting: boolean }>;
  undoUpdate(): Promise<{ restarting: boolean }>;
  dismissUpdateNotice(): Promise<EngineUpdates>;
  // The setup guide and its checks (B130).
  setup(): Promise<SetupState>;
  finishSetup(): Promise<SetupState>;
  useLocalOnly(): Promise<SetupState>;
  setupChecks(): Promise<{ checks: SetupCheck[] }>;
  setupReport(): Promise<SetupReport>;
  health(): Promise<Health>;
  reportVisibility(visible: boolean): Promise<null>;
  vapidKey(): Promise<{ public_key: string }>;
  subscribePush(subscription: PushSubscriptionBody): Promise<null>;
  unsubscribePush(endpoint: string): Promise<null>;
  testPush(): Promise<PushReport>;
  // How many devices that are not revoked receive push notifications.
  pushStatus(): Promise<{ devices: number }>;
  notificationSettings(): Promise<NotificationSettings>;
  saveNotificationSettings(settings: NotificationSettings): Promise<NotificationSettings>;
  // Claude's models, or with `provider` that engine's (Codex's is empty until it answers).
  models(provider?: string): Promise<ModelList>;
  // The engines chats run on; `refresh` asks Codex for its login now.
  providers(refresh?: boolean): Promise<ProviderList>;
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
  // Every skill a pixie may be given (B85).
  pixieSkills(): Promise<PixieSkill[]>;
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
  // Settings (B81, D104).
  branches(repo: string): Promise<{ branches: string[] }>;
  // The project's branches and worktrees, each under the branch it comes from (B96).
  branchMap(repo: string): Promise<BranchMap>;
  // Where the project's new chats start (B131); announced as `repo.updated`.
  selectPlace(repo: string, body: SelectPlaceBody): Promise<RepoConfig>;
  // Clears only a place marked gone, so a selection made meanwhile stays.
  clearGonePlace(repo: string): Promise<RepoConfig>;
  // Fetches every remote, reporting each one; `repo.branches_changed` follows.
  refreshRemotes(repo: string): Promise<RemotesRefresh>;
  // Makes a local branch tracking a remote-only one and names it; nothing is checked out.
  trackRemoteBranch(repo: string, remote: string, name: string): Promise<{ branch: string }>;
  storage(): Promise<StorageUsage>;
  storageSettings(): Promise<StorageSettings>;
  saveStorageSettings(settings: StorageSettings): Promise<StorageSettings>;
  // Largest first.
  largeAttachments(limit: number): Promise<StoredAttachment[]>;
  deleteAttachment(id: string): Promise<null>;
  // 202 at once; the index is rebuilt in the background.
  rebuildSearch(): Promise<unknown>;
  // Settings > Performance (B115).
  perf(): Promise<PerfView>;
  // Starts a run of `sections`, every daemon section when empty; 409 while one runs.
  runPerf(sections: string[]): Promise<PerfView>;
  // Keeps each section's two latest runs.
  clearPerf(): Promise<PerfView>;
  usageSettings(): Promise<UsageSettings>;
  saveUsageSettings(settings: UsageSettings): Promise<UsageSettings>;
  stuckSettings(): Promise<StuckSettings>;
  saveStuckSettings(settings: StuckSettings): Promise<StuckSettings>;
  pixieDefaults(): Promise<PixieDefaults>;
  savePixieDefaults(settings: PixieDefaults): Promise<PixieDefaults>;
  limitSettings(): Promise<LimitSettings>;
  saveLimitSettings(settings: LimitSettings): Promise<LimitSettings>;
  github(): Promise<GithubAccount>;
  checkGithub(): Promise<GithubAccount>;
  claudeAccount(): Promise<ClaudeAccount>;
  // 202 at once; the Mac opens the browser and `account.claude` follows.
  claudeLogin(): Promise<unknown>;
  claudeLogout(): Promise<ClaudeAccount>;
  // Codex's login (B94); signing in happens on the Mac only, its callback being local.
  codexAccount(): Promise<CodexAccount>;
  codexLogout(): Promise<CodexAccount>;
  // An engine's API key (B107, Gemini only), kept in the Mac's Keychain; `account` is an
  // account id such as "gemini-main". Removing it signs the engine out.
  saveEngineKey(account: string, key: string): Promise<unknown>;
  removeEngineKey(account: string): Promise<unknown>;
  // Every engine's accounts (B98, D124); `accounts.changed` carries the same body.
  accounts(): Promise<AccountList>;
  // New usage windows for every signed-in account; 429 within 20 s of the last.
  refreshAccounts(): Promise<AccountList>;
  // Adds an account after the engine's others and starts signing in to it (202); 409 while
  // another sign in of the engine runs.
  addAccount(provider: AccountProvider): Promise<AccountSignIn>;
  signInAccount(id: string): Promise<AccountSignIn>;
  cancelAccountSignIn(id: string): Promise<null>;
  signOutAccount(id: string): Promise<EngineAccount>;
  // 1 to 40 characters; null or "" clears it.
  renameAccount(id: string, name: string | null): Promise<EngineAccount>;
  // The engine's turns start on it from now; 409 unless signed in.
  activateAccount(id: string): Promise<AccountList>;
  // 409 for the engine's first account.
  removeAccount(id: string): Promise<AccountList>;
  // A Codex account's banked resets with each credit; 409 for a Claude account.
  bankedResets(id: string): Promise<BankedResets>;
  // 409 unless a signed-in Codex account, 502 when Codex fails.
  useBankedReset(id: string, creditId: string): Promise<BankedResetUsed>;
  // Local models (B106, D129); `local_models.changed` says to list them again.
  localModels(): Promise<LocalModelList>;
  // Servers on this Mac's usual ports and the models downloaded on it.
  findLocalModels(): Promise<FoundModels>;
  // 422 for an address that is none.
  checkLocalServer(address: string, key: string | null): Promise<CheckResult>;
  // 409 `local_server_down` when the server does not answer, 422 for a model it does not
  // serve; a key goes to the Mac's Keychain.
  addLocalModels(address: string, key: string | null, models: string[]): Promise<AddedLocalModels>;
  removeLocalModel(id: string): Promise<null>;
  setLocalEngine(engine: LocalEngine): Promise<null>;
  // 202 at once; 404 when the app is not installed.
  startLocalServer(app: LocalApp): Promise<null>;
  localUsage(): Promise<LocalUsage>;
  // 202 at once; `engine.state` events follow.
  installEngine(engine: string): Promise<unknown>;
  // 202 at once; `claude_code.install` events follow.
  installClaudeCode(): Promise<unknown>;
  devices(): Promise<ListedDevice[]>;
  revokeDevice(id: string): Promise<null>;
  pairingCode(): Promise<PairingCode>;
  // Settings > Features (B103), with what is new on this device.
  features(): Promise<FeaturesCatalog>;
  // The features this device shows (1 to 500 ids); answers the catalog as `features`.
  markFeaturesSeen(ids: string[]): Promise<FeaturesCatalog>;
  // Claude Code's plugins, skills and marketplaces (D104); writes answer 204.
  plugins(): Promise<InstalledPlugin[]>;
  marketplaces(): Promise<Marketplace[]>;
  addMarketplace(source: string): Promise<null>;
  removeMarketplace(name: string): Promise<null>;
  availablePlugins(): Promise<AvailablePlugin[]>;
  pluginDetails(id: string): Promise<PluginDetails>;
  installPlugin(id: string): Promise<null>;
  uninstallPlugin(id: string): Promise<null>;
  setPluginEnabled(id: string, enabled: boolean): Promise<null>;
  // Newest first, at most 500 (B79).
  artifacts(filter: ArtifactFilter): Promise<Artifact[]>;
  // Artifacts of every project whose latest version is not opened yet.
  artifactsUnseen(): Promise<{ unseen: number }>;
  artifact(id: string): Promise<ArtifactDetail>;
  artifactVersion(id: string, version: number): Promise<ArtifactContent>;
  markArtifactSeen(id: string): Promise<Artifact>;
  deleteArtifact(id: string): Promise<null>;
  artifactStorage(id: string): Promise<ArtifactStorage>;
  /** 413 when the result would be over a cap. */
  writeArtifactStorage(id: string, body: ArtifactStorageWrite): Promise<{ size: number }>;
  clearArtifactStorage(id: string): Promise<unknown>;
  askStatus(id: string): Promise<AskStatus>;
  /** 429 when today's asks are used, 403 when asking is off, 409 while one runs. */
  askArtifact(id: string, body: { prompt: string; system?: string }): Promise<ArtifactAnswer>;
  /** The user's edit of a document (B88); 409 when `base_version` is no longer the latest. */
  saveArtifactVersion(
    id: string,
    body: { content: string; base_version: number },
  ): Promise<ArtifactVersion>;
  // Settings > Configuration (B97). 403 for a path outside the allow-list, 404 for an
  // unknown item, 409 for a conflict, 422 for invalid input.
  configuration(): Promise<ConfigurationPage>;
  configurationFile(path: string): Promise<FileText>;
  // 409 with `current_version` when the file changed since it was read.
  writeConfigurationFile(
    path: string,
    text: string,
    expectedVersion: string | null,
  ): Promise<{ version: string }>;
  setUsesShared(engine: EngineId, item: SharedItem, on: boolean): Promise<ConfigurationPage>;
  createSkill(name: string, description: string): Promise<ConfigurationPage>;
  deleteSkill(name: string): Promise<ConfigurationPage>;
  // Moves a Codex skill into the shared folder.
  makeSkillShared(name: string): Promise<ConfigurationPage>;
  setCodexSkill(name: string, enabled: boolean): Promise<ConfigurationPage>;
  mcpServer(name: string): Promise<McpServer>;
  putMcpServer(name: string, server: McpServer): Promise<ConfigurationPage>;
  deleteMcpServer(name: string): Promise<ConfigurationPage>;
  copyPreview(engine: EngineId): Promise<CopyPreview>;
  // `instructions` false keeps the shared instructions as they are.
  copyToShared(engine: EngineId, instructions: boolean): Promise<CopyResult>;
  undoCopy(undoId: string): Promise<ConfigurationPage>;
  codexPlugins(query: string): Promise<CodexPlugins>;
  installCodexPlugin(id: string): Promise<CodexPlugins>;
  uninstallCodexPlugin(id: string): Promise<CodexPlugins>;
  codexMarketplaces(): Promise<CodexMarketplace[]>;
  addCodexMarketplace(source: string): Promise<CodexMarketplace[]>;
  removeCodexMarketplace(name: string): Promise<CodexMarketplace[]>;
  projectConfiguration(repo: string): Promise<ProjectConfiguration>;
  putProjectMcpServer(repo: string, server: string, body: McpServer): Promise<ProjectConfiguration>;
  deleteProjectMcpServer(repo: string, server: string): Promise<ProjectConfiguration>;
  createProjectSkill(
    repo: string,
    name: string,
    description: string,
  ): Promise<ProjectConfiguration>;
}

// Search results asked for at once; the daemon allows up to 100.
export const SEARCH_LIMIT = 50;

const session = (id: string) => `/api/sessions/${encodeURIComponent(id)}`;
const repo = (name: string) => `/api/repos/${encodeURIComponent(name)}`;
const EXTENSIONS = "/api/extensions";
const plugin = (id: string) => `${EXTENSIONS}/plugins/${encodeURIComponent(id)}`;
const claudeChat = (id: string) => `/api/claude-chats/${encodeURIComponent(id)}`;
const artifact = (id: string) => `/api/artifacts/${encodeURIComponent(id)}`;
const CONFIGURATION = "/api/configuration";
const skill = (name: string) => `${CONFIGURATION}/skills/${encodeURIComponent(name)}`;
const server = (name: string) => `${CONFIGURATION}/mcp-servers/${encodeURIComponent(name)}`;
const codexPlugin = (id: string) => `${CONFIGURATION}/codex/plugins/${encodeURIComponent(id)}`;
const CODEX_MARKETPLACES = `${CONFIGURATION}/codex/marketplaces`;
const engineQuery = (provider: string) => `provider=${encodeURIComponent(provider)}`;
const ACCOUNTS = "/api/accounts";
const account = (id: string) => `${ACCOUNTS}/${encodeURIComponent(id)}`;
const LOCAL = "/api/local";

/**
 * A daemon reached at another origin, as the desktop app does (B117): requests go to `base`
 * (such as "http://127.0.0.1:8765") with the token as a Bearer header and no cookies.
 */
export interface DaemonEndpoint {
  base: string;
  token: string;
}

/**
 * The daemon's REST API. In the phone app the device token travels in the same-origin
 * cookie; with an endpoint it is sent as a Bearer token instead.
 */
export class HttpApi implements Api {
  private readonly fetchFn: typeof fetch;
  private readonly endpoint: DaemonEndpoint | null;

  constructor(
    fetchFn: typeof fetch = (input, init) => fetch(input, init),
    endpoint: DaemonEndpoint | null = null,
  ) {
    this.fetchFn = fetchFn;
    this.endpoint = endpoint;
  }

  private request(path: string, init: RequestInit): Promise<Response> {
    if (this.endpoint === null) return this.fetchFn(path, { ...init, credentials: "same-origin" });
    const headers = new Headers(init.headers);
    headers.set("Authorization", `Bearer ${this.endpoint.token}`);
    return this.fetchFn(`${this.endpoint.base}${path}`, { ...init, headers, credentials: "omit" });
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

  registerRepo(path: string, name?: string) {
    return this.json<RepoConfig>(
      "POST",
      "/api/repos",
      name === undefined ? { path } : { path, name },
    );
  }

  removeRepo(name: string, purge: boolean) {
    return this.json<null>("DELETE", `${repo(name)}?purge_sessions=${String(purge)}`);
  }

  updateRepo(name: string, patch: RepoPatch) {
    return this.json<RepoConfig>("PATCH", repo(name), patch);
  }

  reorderRepos(order: string[]) {
    return this.json<RepoConfig[]>("PUT", "/api/repos/order", { order });
  }

  openRepo(name: string, app: RepoApp) {
    return this.json<null>("POST", `${repo(name)}/open`, { app });
  }

  linkSuggestions(name: string) {
    return this.json<string[]>("GET", `${repo(name)}/link-suggestions`);
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

  openInClaudeCode(id: string) {
    return this.json<{ launcher: string; warning: string | null }>(
      "POST",
      `${session(id)}/open-in-claude-code`,
    );
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

  resumeLimit(id: string) {
    return this.json<Session>("POST", `${session(id)}/limit/resume`);
  }

  setAutopilot(id: string, body: SetAutopilot) {
    return this.json<Session>("PUT", `${session(id)}/autopilot`, body);
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

  refreshPr(sessionId: string) {
    return this.json<Session>("POST", `${session(sessionId)}/pr/refresh`);
  }

  reviewFeedback(sessionId: string, ids?: string[]) {
    const body = ids === undefined ? undefined : { ids };
    return this.json<SendResponse>("POST", `${session(sessionId)}/pr/review-feedback`, body);
  }

  setReviewAutoSend(sessionId: string, autoSend: boolean) {
    return this.json<Session>("PATCH", `${session(sessionId)}/pr/review`, {
      auto_send: autoSend,
    });
  }

  issues(name: string, show?: IssueShow, refresh = false) {
    const query = new URLSearchParams();
    if (show !== undefined) query.set("show", show);
    if (refresh) query.set("refresh", "true");
    const text = query.toString();
    return this.json<IssueList>("GET", `${repo(name)}/issues${text ? `?${text}` : ""}`);
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
    const response = await this.request(path, {});
    if (!response.ok) throw failure(response.status, parse(await response.text()));
    return response.blob();
  }

  /** Whether a stored file is still there (404 otherwise), without reading all of it. */
  async attachmentThere(id: string): Promise<void> {
    const path = `/api/attachments/${encodeURIComponent(id)}`;
    const response = await this.request(path, {});
    if (!response.ok) throw failure(response.status, parse(await response.text()));
    await response.body?.cancel();
  }

  run(sessionId: string) {
    return this.json<RunStatus>("GET", `${session(sessionId)}/run`);
  }

  runControl(sessionId: string, verb: RunVerb) {
    return this.json<RunStatus>("POST", `${session(sessionId)}/run/${verb}`);
  }

  runOutput(sessionId: string) {
    return this.json<RunOutput>("GET", `${session(sessionId)}/run/output`);
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

  usagePeriod(unit: PeriodUnit, date: string) {
    return this.json<UsagePeriod>("GET", `/api/usage/period?unit=${unit}&date=${date}`);
  }

  usageLimits() {
    return this.json<UsageLimits>("GET", "/api/usage/limits");
  }

  /** Asks Claude for fresh limits now; 429 within 20 s of the last refresh. */
  refreshUsage() {
    return this.json<UsageLimits>("POST", "/api/usage/refresh");
  }

  engineLimits(provider: string) {
    return this.json<EngineLimits>("GET", `/api/usage/limits?${engineQuery(provider)}`);
  }

  refreshEngineUsage(provider: string) {
    return this.json<EngineLimits>("POST", `/api/usage/refresh?${engineQuery(provider)}`);
  }

  restartService() {
    return this.json<{ restarting: boolean }>("POST", "/api/service/restart");
  }

  updates() {
    return this.json<EngineUpdates>("GET", "/api/updates");
  }

  checkUpdates() {
    return this.json<EngineUpdates>("POST", "/api/updates/check");
  }

  relaunchUpdate() {
    return this.json<{ restarting: boolean }>("POST", "/api/updates/relaunch");
  }

  undoUpdate() {
    return this.json<{ restarting: boolean }>("POST", "/api/updates/undo");
  }

  dismissUpdateNotice() {
    return this.json<EngineUpdates>("POST", "/api/updates/dismiss");
  }

  setup() {
    return this.json<SetupState>("GET", "/api/setup");
  }

  finishSetup() {
    return this.json<SetupState>("POST", "/api/setup/done");
  }

  useLocalOnly() {
    return this.json<SetupState>("POST", "/api/setup/local-only");
  }

  setupChecks() {
    return this.json<{ checks: SetupCheck[] }>("GET", "/api/setup/checks");
  }

  setupReport() {
    return this.json<SetupReport>("POST", "/api/setup/report");
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

  pushStatus() {
    return this.json<{ devices: number }>("GET", "/api/push/status");
  }

  notificationSettings() {
    return this.json<NotificationSettings>("GET", "/api/notifications/settings");
  }

  saveNotificationSettings(settings: NotificationSettings) {
    return this.json<NotificationSettings>("PUT", "/api/notifications/settings", settings);
  }

  models(provider?: string) {
    const query = provider === undefined ? "" : `?${engineQuery(provider)}`;
    return this.json<ModelList>("GET", `/api/models${query}`);
  }

  providers(refresh = false) {
    return this.json<ProviderList>("GET", `/api/providers${refresh ? "?refresh=true" : ""}`);
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

  pixieSkills() {
    return this.json<PixieSkill[]>("GET", "/api/pixies/skills");
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

  branches(name: string) {
    return this.json<{ branches: string[] }>("GET", `${repo(name)}/branches`);
  }

  branchMap(name: string) {
    return this.json<BranchMap>("GET", `${repo(name)}/branch-map`);
  }

  selectPlace(name: string, body: SelectPlaceBody) {
    return this.json<RepoConfig>("PUT", `${repo(name)}/selected-place`, body);
  }

  clearGonePlace(name: string) {
    return this.json<RepoConfig>("DELETE", `${repo(name)}/selected-place/gone`);
  }

  refreshRemotes(name: string) {
    return this.json<RemotesRefresh>("POST", `${repo(name)}/refresh`);
  }

  trackRemoteBranch(name: string, remote: string, branch: string) {
    return this.json<{ branch: string }>("POST", `${repo(name)}/remote-branches`, {
      remote,
      name: branch,
    });
  }

  storage() {
    return this.json<StorageUsage>("GET", "/api/storage");
  }

  storageSettings() {
    return this.json<StorageSettings>("GET", "/api/storage/settings");
  }

  saveStorageSettings(settings: StorageSettings) {
    return this.json<StorageSettings>("PUT", "/api/storage/settings", settings);
  }

  largeAttachments(limit: number) {
    return this.json<StoredAttachment[]>("GET", `/api/storage/attachments?limit=${String(limit)}`);
  }

  deleteAttachment(id: string) {
    return this.json<null>("DELETE", `/api/attachments/${encodeURIComponent(id)}`);
  }

  rebuildSearch() {
    return this.json<unknown>("POST", "/api/search/rebuild");
  }

  perf() {
    return this.json<PerfView>("GET", "/api/perf");
  }

  runPerf(sections: string[]) {
    return this.json<PerfView>("POST", "/api/perf/runs", { sections });
  }

  clearPerf() {
    return this.json<PerfView>("POST", "/api/perf/clear");
  }

  usageSettings() {
    return this.json<UsageSettings>("GET", "/api/usage/settings");
  }

  saveUsageSettings(settings: UsageSettings) {
    return this.json<UsageSettings>("PUT", "/api/usage/settings", settings);
  }

  stuckSettings() {
    return this.json<StuckSettings>("GET", "/api/stuck/settings");
  }

  saveStuckSettings(settings: StuckSettings) {
    return this.json<StuckSettings>("PUT", "/api/stuck/settings", settings);
  }

  pixieDefaults() {
    return this.json<PixieDefaults>("GET", "/api/pixie-settings");
  }

  savePixieDefaults(settings: PixieDefaults) {
    return this.json<PixieDefaults>("PUT", "/api/pixie-settings", settings);
  }

  limitSettings() {
    return this.json<LimitSettings>("GET", "/api/limits/settings");
  }

  saveLimitSettings(settings: LimitSettings) {
    return this.json<LimitSettings>("PUT", "/api/limits/settings", settings);
  }

  github() {
    return this.json<GithubAccount>("GET", "/api/accounts/github");
  }

  checkGithub() {
    return this.json<GithubAccount>("POST", "/api/accounts/github/check");
  }

  claudeAccount() {
    return this.json<ClaudeAccount>("GET", "/api/accounts/claude");
  }

  claudeLogin() {
    return this.json<unknown>("POST", "/api/accounts/claude/login");
  }

  claudeLogout() {
    return this.json<ClaudeAccount>("POST", "/api/accounts/claude/logout");
  }

  installClaudeCode() {
    return this.json<unknown>("POST", "/api/claude-code/install");
  }

  devices() {
    return this.json<ListedDevice[]>("GET", "/api/devices");
  }

  revokeDevice(id: string) {
    return this.json<null>("DELETE", `/api/devices/${encodeURIComponent(id)}`);
  }

  pairingCode() {
    return this.json<PairingCode>("POST", "/api/pairing/codes");
  }

  features() {
    return this.json<FeaturesCatalog>("GET", "/api/features");
  }

  markFeaturesSeen(ids: string[]) {
    return this.json<FeaturesCatalog>("POST", "/api/features/seen", { ids });
  }

  plugins() {
    return this.json<InstalledPlugin[]>("GET", `${EXTENSIONS}/plugins`);
  }

  marketplaces() {
    return this.json<Marketplace[]>("GET", `${EXTENSIONS}/marketplaces`);
  }

  addMarketplace(source: string) {
    return this.json<null>("POST", `${EXTENSIONS}/marketplaces`, { source });
  }

  removeMarketplace(name: string) {
    return this.json<null>("DELETE", `${EXTENSIONS}/marketplaces/${encodeURIComponent(name)}`);
  }

  availablePlugins() {
    return this.json<AvailablePlugin[]>("GET", `${EXTENSIONS}/available`);
  }

  pluginDetails(id: string) {
    return this.json<PluginDetails>("GET", `${plugin(id)}/details`);
  }

  installPlugin(id: string) {
    return this.json<null>("POST", `${plugin(id)}/install`);
  }

  uninstallPlugin(id: string) {
    return this.json<null>("POST", `${plugin(id)}/uninstall`);
  }

  setPluginEnabled(id: string, enabled: boolean) {
    return this.json<null>("PUT", `${plugin(id)}/enabled`, { enabled });
  }

  artifacts(filter: ArtifactFilter) {
    const query = new URLSearchParams(Object.entries(filter)).toString();
    return this.json<Artifact[]>("GET", query ? `/api/artifacts?${query}` : "/api/artifacts");
  }

  artifactsUnseen() {
    return this.json<{ unseen: number }>("GET", "/api/artifacts/unseen");
  }

  artifact(id: string) {
    return this.json<ArtifactDetail>("GET", artifact(id));
  }

  artifactVersion(id: string, version: number) {
    return this.json<ArtifactContent>("GET", `${artifact(id)}/versions/${String(version)}`);
  }

  markArtifactSeen(id: string) {
    return this.json<Artifact>("POST", `${artifact(id)}/seen`);
  }

  deleteArtifact(id: string) {
    return this.json<null>("DELETE", artifact(id));
  }

  artifactStorage(id: string) {
    return this.json<ArtifactStorage>("GET", `${artifact(id)}/storage`);
  }

  writeArtifactStorage(id: string, body: ArtifactStorageWrite) {
    return this.json<{ size: number }>("POST", `${artifact(id)}/storage`, body);
  }

  clearArtifactStorage(id: string) {
    return this.json<unknown>("DELETE", `${artifact(id)}/storage`);
  }

  askStatus(id: string) {
    return this.json<AskStatus>("GET", `${artifact(id)}/ask`);
  }

  askArtifact(id: string, body: { prompt: string; system?: string }) {
    return this.json<ArtifactAnswer>("POST", `${artifact(id)}/ask`, body);
  }

  saveArtifactVersion(id: string, body: { content: string; base_version: number }) {
    return this.json<ArtifactVersion>("POST", `${artifact(id)}/versions`, body);
  }

  codexAccount() {
    return this.json<CodexAccount>("GET", "/api/accounts/codex");
  }

  codexLogout() {
    return this.json<CodexAccount>("POST", "/api/accounts/codex/logout");
  }

  saveEngineKey(account: string, key: string) {
    return this.json<unknown>("PUT", `/api/accounts/${encodeURIComponent(account)}/key`, { key });
  }

  removeEngineKey(account: string) {
    return this.json<unknown>("DELETE", `/api/accounts/${encodeURIComponent(account)}/key`);
  }

  accounts() {
    return this.json<AccountList>("GET", ACCOUNTS);
  }

  refreshAccounts() {
    return this.json<AccountList>("POST", `${ACCOUNTS}/refresh`);
  }

  addAccount(provider: AccountProvider) {
    return this.json<AccountSignIn>("POST", `${ACCOUNTS}/${encodeURIComponent(provider)}`);
  }

  signInAccount(id: string) {
    return this.json<AccountSignIn>("POST", `${account(id)}/login`);
  }

  cancelAccountSignIn(id: string) {
    return this.json<null>("POST", `${account(id)}/login/cancel`);
  }

  signOutAccount(id: string) {
    return this.json<EngineAccount>("POST", `${account(id)}/logout`);
  }

  renameAccount(id: string, name: string | null) {
    return this.json<EngineAccount>("PUT", `${account(id)}/name`, { name });
  }

  activateAccount(id: string) {
    return this.json<AccountList>("PUT", `${account(id)}/active`);
  }

  removeAccount(id: string) {
    return this.json<AccountList>("DELETE", account(id));
  }

  bankedResets(id: string) {
    return this.json<BankedResets>("GET", `${account(id)}/banked-resets`);
  }

  useBankedReset(id: string, creditId: string) {
    return this.json<BankedResetUsed>("POST", `${account(id)}/banked-resets/use`, {
      credit_id: creditId,
    });
  }

  localModels() {
    return this.json<LocalModelList>("GET", `${LOCAL}/models`);
  }

  findLocalModels() {
    return this.json<FoundModels>("GET", `${LOCAL}/find`);
  }

  checkLocalServer(address: string, key: string | null) {
    return this.json<CheckResult>("POST", `${LOCAL}/check`, { address, key });
  }

  addLocalModels(address: string, key: string | null, models: string[]) {
    return this.json<AddedLocalModels>("POST", `${LOCAL}/models`, { address, key, models });
  }

  removeLocalModel(id: string) {
    return this.json<null>("DELETE", `${LOCAL}/models/${encodeURIComponent(id)}`);
  }

  setLocalEngine(engine: LocalEngine) {
    return this.json<null>("PUT", `${LOCAL}/engine`, { engine });
  }

  startLocalServer(app: LocalApp) {
    return this.json<null>("POST", `${LOCAL}/start`, { app });
  }

  localUsage() {
    return this.json<LocalUsage>("GET", `${LOCAL}/usage`);
  }

  installEngine(engine: string) {
    return this.json<unknown>("POST", `/api/engines/${encodeURIComponent(engine)}/install`);
  }

  configuration() {
    return this.json<ConfigurationPage>("GET", CONFIGURATION);
  }

  configurationFile(path: string) {
    return this.json<FileText>("GET", `${CONFIGURATION}/file?path=${encodeURIComponent(path)}`);
  }

  writeConfigurationFile(path: string, text: string, expectedVersion: string | null) {
    return this.json<{ version: string }>("PUT", `${CONFIGURATION}/file`, {
      path,
      text,
      expected_version: expectedVersion,
    });
  }

  setUsesShared(engine: EngineId, item: SharedItem, on: boolean) {
    return this.json<ConfigurationPage>("PUT", `${CONFIGURATION}/uses-shared`, {
      engine,
      item,
      on,
    });
  }

  createSkill(name: string, description: string) {
    return this.json<ConfigurationPage>("POST", `${CONFIGURATION}/skills`, { name, description });
  }

  deleteSkill(name: string) {
    return this.json<ConfigurationPage>("DELETE", skill(name));
  }

  makeSkillShared(name: string) {
    return this.json<ConfigurationPage>("POST", `${skill(name)}/make-shared`, { engine: "codex" });
  }

  setCodexSkill(name: string, enabled: boolean) {
    return this.json<ConfigurationPage>("PUT", `${skill(name)}/engines/codex`, { enabled });
  }

  mcpServer(name: string) {
    return this.json<McpServer>("GET", server(name));
  }

  putMcpServer(name: string, body: McpServer) {
    return this.json<ConfigurationPage>("PUT", server(name), body);
  }

  deleteMcpServer(name: string) {
    return this.json<ConfigurationPage>("DELETE", server(name));
  }

  copyPreview(engine: EngineId) {
    return this.json<CopyPreview>("GET", `${CONFIGURATION}/copy/${engine}`);
  }

  copyToShared(engine: EngineId, instructions: boolean) {
    return this.json<CopyResult>("POST", `${CONFIGURATION}/copy/${engine}`, { instructions });
  }

  undoCopy(undoId: string) {
    return this.json<ConfigurationPage>(
      "POST",
      `${CONFIGURATION}/copy/undo/${encodeURIComponent(undoId)}`,
    );
  }

  codexPlugins(query: string) {
    const search = query === "" ? "" : `?query=${encodeURIComponent(query)}`;
    return this.json<CodexPlugins>("GET", `${CONFIGURATION}/codex/plugins${search}`);
  }

  installCodexPlugin(id: string) {
    return this.json<CodexPlugins>("POST", `${codexPlugin(id)}/install`);
  }

  uninstallCodexPlugin(id: string) {
    return this.json<CodexPlugins>("POST", `${codexPlugin(id)}/uninstall`);
  }

  codexMarketplaces() {
    return this.json<CodexMarketplace[]>("GET", CODEX_MARKETPLACES);
  }

  addCodexMarketplace(source: string) {
    return this.json<CodexMarketplace[]>("POST", CODEX_MARKETPLACES, { source });
  }

  removeCodexMarketplace(name: string) {
    return this.json<CodexMarketplace[]>(
      "DELETE",
      `${CODEX_MARKETPLACES}/${encodeURIComponent(name)}`,
    );
  }

  projectConfiguration(name: string) {
    return this.json<ProjectConfiguration>("GET", `${repo(name)}/configuration`);
  }

  putProjectMcpServer(name: string, serverName: string, body: McpServer) {
    return this.json<ProjectConfiguration>(
      "PUT",
      `${repo(name)}/configuration/mcp-servers/${encodeURIComponent(serverName)}`,
      body,
    );
  }

  deleteProjectMcpServer(name: string, serverName: string) {
    return this.json<ProjectConfiguration>(
      "DELETE",
      `${repo(name)}/configuration/mcp-servers/${encodeURIComponent(serverName)}`,
    );
  }

  createProjectSkill(name: string, skillName: string, description: string) {
    return this.json<ProjectConfiguration>("POST", `${repo(name)}/configuration/skills`, {
      name: skillName,
      description,
    });
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
    const response = await this.request(path, init);
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
