// The daemon's JSON shapes (daemon/src/nestd/**/models.py), field for field.

export type JsonValue =
  string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };
export type JsonObject = Record<string, JsonValue>;

export type SessionState =
  "starting" | "running" | "waiting" | "idle" | "interrupted" | "failed" | "closed";
export type Effort = "low" | "medium" | "high" | "xhigh" | "max";
// "auto" only for models that support it (`ModelOption.supports_auto_mode`).
export type PermissionMode = "default" | "acceptEdits" | "bypassPermissions" | "plan" | "auto";
// How Claude continues after a plan is approved.
export type PlanMode = "acceptEdits" | "default" | "auto";
export type SessionMode = "worktree" | "in_place";

/** How full the conversation's context window is, after the last turn. */
export interface ContextUsage {
  // 0 to 100, may be fractional.
  percent: number;
  used: number;
  limit: number;
}

export type PrState = "open" | "merged" | "closed";
// Skipped and neutral checks never block a merge.
export type CheckState = "pending" | "success" | "failure" | "skipped";
// "none" when the pull request has no checks.
export type ChecksState = "pending" | "success" | "failure" | "none";

export interface PrCheck {
  name: string;
  state: CheckState;
  url: string | null;
}

/** A pull request's last known status on GitHub (D034). */
export interface PrStatus {
  number: number;
  url: string;
  title: string;
  state: PrState;
  checks: {
    state: ChecksState;
    // Skipped checks count as passed.
    passed: number;
    failed: number;
    pending: number;
    items: PrCheck[];
  };
  // Null while GitHub is still working it out.
  mergeable: boolean | null;
  merge_state: string | null;
  review_decision: string | null;
  head_sha: string | null;
  created_at: string | null;
  changed_at: string;
  updated_at: string;
}

export type StuckReason = "waiting" | "silent" | "repeating" | "long_turn";

/** Why a running chat looks stuck (D036). */
export interface StuckFlag {
  // waiting: on a prompt; silent: no output; repeating: the same tool call; long_turn.
  reason: StuckReason;
  // When the condition began.
  since: string;
  // One sentence, such as "No new output for 12 minutes".
  details: string;
}

// Which usage limit paused a chat, as Claude Code names it (B78).
export type PauseWindow =
  "five_hour" | "seven_day" | "seven_day_opus" | "seven_day_sonnet" | "overage";

/** A chat paused at a usage limit until `resume_at`, when the daemon goes on (B78). */
export interface LimitPause {
  // Null when Claude Code did not say; a newer daemon may send names this list lacks.
  window: PauseWindow | null;
  resets_at: string | null;
  resume_at: string;
  since: string;
}

export interface Session {
  id: string;
  repo: string;
  title: string;
  prompt: string;
  mode: SessionMode;
  cwd: string | null;
  model: string | null;
  effort: Effort | null;
  permission_mode: PermissionMode;
  provider: string;
  base_ref: string | null;
  state: SessionState;
  worktree_path: string | null;
  branch: string | null;
  provider_session_id: string | null;
  created_at: string;
  updated_at: string;
  last_error: string | null;
  commit_sha: string | null;
  pr_url: string | null;
  allowed_tools: string[];
  pinned: boolean;
  archived_at: string | null;
  // Null until a turn reported it.
  context: ContextUsage | null;
  // Null until the daemon first read the pull request from GitHub.
  pr: PrStatus | null;
  // Up to three lines about the pull request Nest opened.
  pr_summary: string | null;
  // Set while the chat looks stuck.
  stuck: StuckFlag | null;
  // Set for a pixie's chat (D072).
  pixie_id: string | null;
  // The pixie that started this chat, if one did (B41).
  started_by_pixie: string | null;
  // Set for a habit run's chat (B42): it has the pixie's pixie_id but is not its chat.
  habit_run_id: string | null;
  // Set while the chat waits for a usage limit to reset (B78); the chat is idle meanwhile.
  limit_pause: LimitPause | null;
}

/** A Claude Code chat of a registered repo that Nest does not own (D028). */
export interface ClaudeChat {
  id: string;
  repo: string;
  title: string;
  cwd: string;
  // The Claude Code worktree (<repo>/.claude/worktrees/<name>) it ran in, if any.
  worktree: string | null;
  created_at: string;
  last_activity_at: string;
  message_count: number;
  open_in_claude_code: boolean;
  // What started it, as Claude Code recorded it: "cli", "claude-desktop", "sdk-py"...
  entrypoint: string | null;
  // Started by a program through an Agent SDK; listed only on request.
  automated: boolean;
  // Archived in Nest only (D040); listed with the archived chats.
  archived: boolean;
}

export interface TrackedTask {
  id: string;
  subject: string;
  description: string | null;
  active_form: string | null;
  status: "pending" | "in_progress" | "completed" | "deleted";
}

/** A chat of a project that is working or has a task list showing, with that list (D092). */
export interface Goal {
  session_id: string;
  tasks: TrackedTask[];
}

export interface AgentStep {
  id: string;
  tool: string;
  arg: string;
  result: string | null;
}

export interface TrackedAgent {
  id: string;
  name: string;
  description: string | null;
  // The Agent call of the subagent that started it; null when the main agent did (B46).
  // Daemons before B46 send none.
  parent?: string | null;
  status: "running" | "done" | "failed";
  activity: string | null;
  started_at: string | null;
  finished_at: string | null;
  steps: AgentStep[];
}

/** A subagent or a background command, for the "N running · M completed" bar. */
export interface BackgroundItem {
  // The Agent or Bash tool use id.
  id: string;
  kind: "agent" | "bash";
  // The subagent's type, or the command.
  name: string;
  description: string | null;
  status: TrackedAgent["status"];
  started_at: string | null;
  finished_at: string | null;
}

export interface BackgroundSummary {
  running: number;
  // Finished, whether done or failed.
  completed: number;
  items: BackgroundItem[];
}

export interface QueuedAttachment {
  id: string;
  filename: string;
  media_type: string;
  size: number;
}

/**
 * A message sent while a turn runs that Claude has not read yet (B59): `sent` when it went
 * into the running turn, which reads it at its next step; otherwise it waits for the turn
 * to end (or, after a Stop, for the next message or Send now).
 */
export interface QueuedMessage {
  id: string;
  text: string;
  attachments: QueuedAttachment[];
  created_at: string;
  sent: boolean;
}

export interface SessionDetail extends Session {
  tasks: TrackedTask[];
  agents: TrackedAgent[];
  background: BackgroundSummary;
  // Oldest first.
  queued: QueuedMessage[];
}

/** What sending a message returns: the session, and the queued message when a turn runs. */
export interface SendResponse extends Session {
  queued_message: QueuedMessage | null;
}

/** A slash command or skill; the name has no leading slash. */
export interface SlashCommand {
  name: string;
  description: string | null;
  argument_hint: string | null;
}

export interface CommandAgent {
  name: string;
  description: string | null;
}

export interface CommandList {
  // Where the list came from: this session's agent, the repo's last known list, or nowhere.
  source: "session" | "repo" | "none";
  // Sorted by name.
  commands: SlashCommand[];
  agents: CommandAgent[];
  updated_at: string | null;
}

export type ApprovalKind =
  | "permission"
  | "question"
  | "review"
  | "plan"
  | "merge"
  // Pull request review comments waiting to go to the agent (B101).
  | "review_comments";
export type ApprovalStatus = "pending" | "resolved" | "expired" | "superseded";

export interface Approval {
  id: string;
  session_id: string;
  repo: string;
  title: string;
  kind: ApprovalKind;
  status: ApprovalStatus;
  payload: JsonObject;
  resolution: JsonObject | null;
  created_at: string;
  resolved_at: string | null;
}

export interface WorktreeConfig {
  // Null follows the agent default ("New chats work in"); true or false overrides it.
  default: boolean | null;
  link: string[];
  setup: string[];
  setup_timeout_seconds: number;
}

export interface RepoConfig {
  name: string;
  path: string;
  // False for a plain folder outside git (D041): its chats work in place, nothing to review.
  git: boolean;
  // Null for a plain folder.
  default_branch: string | null;
  // The branch checked out in the folder when the repo was read; null when HEAD is
  // detached, the branch has no commits yet, or the folder is not git (B55).
  current_branch: string | null;
  // The only address Nest pushes origin to (D050); null when none is recorded.
  remote_url: string | null;
  // A pixie sprite as the project's icon; null shows its initials (B36).
  icon: Mascot | null;
  // Null is the default colour.
  icon_color: string | null;
  worktree: WorktreeConfig;
}

export interface DiffLine {
  kind: "context" | "add" | "delete";
  text: string;
  old_line: number | null;
  new_line: number | null;
}

export interface Hunk {
  old_start: number;
  old_lines: number;
  new_start: number;
  new_lines: number;
  header: string;
  lines: DiffLine[];
}

export interface FileDiff {
  path: string;
  old_path: string | null;
  status: "added" | "modified" | "deleted" | "renamed";
  additions: number;
  deletions: number;
  binary: boolean;
  truncated: boolean;
  // A nested git repository inside the work: shown, but never committed (approval is refused).
  nested_repository: boolean;
  hunks: Hunk[];
}

export interface DiffStats {
  files: number;
  additions: number;
  deletions: number;
}

// The commit and branch a publish would use. The commit is null when HEAD is detached or
// unborn (no commits yet); the branch is null only when HEAD is detached.
export interface ReviewHead {
  commit: string | null;
  branch: string | null;
}

export interface SessionDiff {
  base: string | null;
  head: ReviewHead;
  files: FileDiff[];
  stats: DiffStats;
  // A hash of everything shown; approving sends it back as `expected_fingerprint`.
  fingerprint: string;
}

export interface TokenTotals {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  total: number;
}

// A calendar period of counted usage, by the Mac's local calendar; weeks start on Monday.
export type PeriodUnit = "day" | "week" | "month" | "year";

export interface UsageBar {
  // The bar's local start with its UTC offset: an hour, a day or a month.
  start: string;
  tokens: number;
  sessions: number;
}

export interface ProjectUsage {
  name: string;
  tokens: number;
  // Every pixie chat counted as one "Pixies" entry.
  pixies: boolean;
}

export interface UsagePeriod {
  unit: PeriodUnit;
  start: string;
  end: string;
  // The period holds today.
  current: boolean;
  sessions: number;
  // Everything: the chats and their subagents.
  tokens: TokenTotals;
  // The subagents' part of `tokens`.
  subagents: TokenTotals;
  bars: UsageBar[];
  projects: ProjectUsage[];
  // The Mac's own usage checks, not counted in `tokens`.
  probes: { count: number; tokens: number };
  // By engine, Claude first, then by name; none without tokens (B91). Older daemons send none.
  engines?: EngineUsage[];
}

/** One engine's part of a period's tokens (B91). */
export interface EngineUsage {
  provider: string;
  tokens: number;
  sessions: number;
}

export interface LimitWindow {
  // A fraction: 0.3 is 30%.
  utilization: number;
  resets_at: string | null;
  updated_at: string;
}

export interface UsageLimits {
  five_hour: LimitWindow | null;
  seven_day: LimitWindow | null;
}

/** One of another engine's windows, by its length (B91: Codex). */
export interface EngineLimitWindow extends LimitWindow {
  // Null when the engine left the length out.
  minutes: number | null;
  // What clients call it: "5 hour", "Weekly", "30 day", or "Usage" without a length.
  label: string;
}

/** Another engine's windows, whichever its plan has, shortest first (B91). */
export interface EngineLimits {
  windows: EngineLimitWindow[];
}

export interface Connector {
  name: string;
  display_name: string;
  group: "claude.ai" | "plugin" | "local";
  status: string;
  error: string | null;
  manage_hint: "claude.ai" | "claude_code";
  source: string;
  last_seen_at: string;
}

export interface Device {
  id: string;
  name: string;
  is_local: boolean;
  created_at: string;
  last_seen_at: string | null;
  revoked_at: string | null;
}

/** A device in `GET /api/devices`, which marks the device asking (B81). */
export interface ListedDevice extends Device {
  this_device: boolean;
}

export interface RedeemResponse {
  device: Device;
  token: string;
}

export interface Attachment {
  id: string;
  filename: string;
  media_type: string;
  size: number;
  created_at: string;
}

export interface NestEvent {
  // Null for ephemeral events (text deltas), which are never stored or replayed.
  id: number | null;
  type: string;
  ts: string;
  session_id: string | null;
  payload: JsonObject;
}

export interface CreateSessionBody {
  repo: string;
  prompt: string;
  // The engine (B91); left out, the agent defaults' engine.
  provider?: string;
  model?: string;
  effort?: Effort;
  permission_mode?: PermissionMode;
  attachment_ids?: string[];
  mode?: SessionMode;
  // Worktree chats only (B55): the local branch to start from, and the new branch's name.
  base?: string;
  branch?: string;
}

export interface UpdateSessionBody {
  model?: string;
  // Applies when the agent next opens: from the next message of an idle chat.
  effort?: Effort;
  permission_mode?: PermissionMode;
  title?: string;
  pinned?: boolean;
  archived?: boolean;
}

export interface ResolveBody {
  // Merge approvals only: put the card away without merging.
  dismiss?: boolean;
  behavior?: "allow" | "deny";
  always?: boolean;
  answers?: Record<string, string | string[]>;
  // Plans only; a note to Claude goes with "keep_planning".
  decision?: "approve" | "keep_planning";
  message?: string | null;
  // Plans only, with "approve": the permission mode Claude continues in.
  mode?: PlanMode;
}

export interface ApproveBody {
  commit_message: string;
  files?: string[];
  open_pr?: boolean;
  // False commits without pushing, as for in-place chats (B56); the daemon pushes by default.
  push?: boolean;
  // The HEAD the user reviewed; the daemon refuses with `head_changed` if it moved.
  expected_head?: string;
  // The reviewed diff's fingerprint; the daemon refuses with `review_changed` if it differs.
  expected_fingerprint: string;
  // The push address the user confirmed after a `remote_not_confirmed` or `remote_changed`.
  confirm_remote_url?: string;
}

/** What a rewind restores (B59): the files, the conversation, or both. */
export type Restore = "code" | "conversation" | "both";

/** What rewinding to before a message would do (`GET .../rewind?message=&restore=`). */
export interface RewindPreview {
  can_rewind: boolean;
  // The paths, or only how many (the SDK reports paths; a count is accepted too).
  files_changed: string[] | number;
  insertions: number;
  deletions: number;
  // Why it cannot be done, when it cannot.
  error: string | null;
}

/** What a rewind did; `text` and `attachments` are the rewound message, for the composer. */
export interface RewindReply extends RewindPreview {
  restore: Restore;
  text: string | null;
  attachments: QueuedAttachment[];
}

/** A `!` command run in the chat's folder (B59); `context` goes before the next message. */
export interface ShellResult {
  command: string;
  // Null when it timed out.
  exit_code: number | null;
  output: string;
  truncated: boolean;
  timed_out: boolean;
  context: string;
}

/** Where a `#` memory goes (B59): the project's CLAUDE.md, or the user's. */
export type MemoryScope = "project" | "user";

export interface MemoryReply {
  // The file written.
  path: string;
  scope: MemoryScope;
  line: string;
}

/** A chat forked from a message (B59), with that message for its composer. */
export interface ForkReply {
  session: Session;
  text: string;
  attachments: QueuedAttachment[];
}

/** Project settings to change (`PATCH /api/repos/{name}`); only the keys sent change. */
export interface RepoPatch {
  default?: boolean | null;
  link?: string[];
  setup?: string[];
  icon?: Mascot | null;
  icon_color?: string | null;
  // Git repositories only (D104): an existing local branch, and the push address.
  default_branch?: string;
  remote_url?: string | null;
  setup_timeout_seconds?: number;
}

export type NotifyKind =
  | "needs_approval"
  | "question"
  | "review_ready"
  | "failed"
  | "finished"
  | "ci_failed"
  | "ready_to_merge"
  | "stuck"
  | "pixie_report"
  | "usage_limit";

export type SearchHitKind = "title" | "user" | "assistant" | "tool" | "tool_result" | "claude_chat";

/** A chat title or message matching a search (D035). */
export interface SearchHit {
  // A Nest session, or a Claude Code chat id for kind "claude_chat".
  session_id: string;
  repo: string;
  title: string;
  // The event to scroll to; null for title matches.
  event_id: number | null;
  ts: string;
  kind: SearchHitKind;
  // Matched words are wrapped in [[ and ]].
  snippet: string;
}

export interface SearchResults {
  // Best match first.
  hits: SearchHit[];
  // True while the Mac still indexes older history.
  indexing: boolean;
}

export interface MergeBody {
  method?: "squash" | "merge" | "rebase";
  delete_branch?: boolean;
}

export interface QuietHours {
  // "HH:MM" in the Mac's local time.
  start: string;
  end: string;
}

/** The [notifications] section of the daemon's settings.toml; PUT sends it back whole. */
export interface NotificationSettings {
  kinds: Record<NotifyKind, boolean>;
  // The least severe pixie report pushed to the phone, for every pixie (B85).
  pixie_report_level: ReportSeverity;
  quiet_hours: QuietHours | null;
  ntfy: {
    enabled: boolean;
    server: string;
    topic: string | null;
    click_base_url: string | null;
  };
  vapid_subject: string;
}

/** What PushSubscription.toJSON() gives. */
export interface PushSubscriptionBody {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export interface PushReport {
  sent: number;
  failed: number;
  removed: number;
}

/** A model Claude Code offers, in its own order (`GET /api/models`). */
export interface ModelOption {
  // What a chat's `model` is set to: "default", "opus", "claude-opus-4-8"...
  value: string;
  display_name: string;
  description: string;
  // Empty when the model takes no thinking level (Haiku).
  effort_levels: string[];
  supports_effort: boolean;
  // Whether the model takes the "auto" permission mode.
  supports_auto_mode: boolean;
  // The model id the engine resolves `value` to, such as "claude-sonnet-5-5".
  resolved_model?: string | null;
  // The thinking level Claude Code's own settings give it, when they set one.
  claude_code_effort: string | null;
}

export interface ModelList {
  // Real models only: the engine's "default" entry is never offered (B94).
  models: ModelOption[];
  // Null while the Mac has only Claude Code's aliases to offer.
  updated_at: string | null;
  // The model the engine runs when none is named, as a value of `models`; null while the
  // engine has not said (B94). A chat without a model reads as this one.
  default_model: string | null;
}

/** What an engine's chats cannot do (B91); clients hide it, the daemon refuses it. */
export type ProviderFeature =
  | "rewind"
  | "fork"
  | "slash_commands"
  | "stop_task"
  | "withdraw"
  | "plan_review"
  | "questions"
  | "subagents"
  | "nest_tools"
  | "task_list"
  | "pixies"
  | "memory"
  | "pixie_skills";

/** An engine a new chat can run on (`GET /api/providers`, B91), the default one first. */
export interface ProviderInfo {
  // What a chat's `provider` is set to: "claude" or "codex".
  name: string;
  display_name: string;
  // Null when Nest does not check (Claude) or Codex could not be asked; Codex stays
  // offered when false, and its chats fail until the user signs in.
  signed_in: boolean | null;
  // What to tell the user when `signed_in` is false.
  sign_in_hint: string | null;
  account: AccountInfo | null;
  unsupported: ProviderFeature[];
}

export interface ProviderList {
  providers: ProviderInfo[];
}

/** Who Claude Code is signed in as; every field may be unknown. */
export interface AccountInfo {
  display_name: string | null;
  email: string | null;
  plan: string | null;
  organization: string | null;
}

/**
 * What new chats use unless the composer chooses otherwise. Served concrete (B94): a null
 * model only while no engine reported its list, a null effort only for a model without
 * thinking levels. Nulls sent are what Nest picks: the first engine signed in, its default
 * model, Medium (or the closest level), Ask.
 */
export interface AgentDefaults {
  // The engine, such as "claude" or "codex"; daemons before B94 send none.
  provider?: string | null;
  model: string | null;
  effort: Effort | null;
  permission_mode: PermissionMode | null;
  mode: SessionMode;
}

/** Codex's own login on the Mac (`GET /api/accounts/codex`, B94); never a token. */
export interface CodexAccount {
  // Null when Codex could not be asked; `error` then says why, in a word.
  signed_in: boolean | null;
  email: string | null;
  // Such as "ChatGPT Plus".
  plan: string | null;
  checked_at: string;
  // On an `account.codex` event: why signing in failed, else null.
  error?: string | null;
}

export type Mascot =
  | "bluebell"
  | "dragonfly"
  | "moth"
  | "firefly"
  | "rose"
  | "frost"
  | "sprig"
  | "nightshade"
  | "brook"
  | "star";
export type Autonomy = "observe" | "message" | "start" | "answer";
export type ProjectAccess = "edit" | "read" | "none";

/** Everything the user sets on a pixie (D072). */
export interface PixieSettings {
  name: string;
  mascot: Mascot;
  color: string;
  // The engine it runs on (B91): "claude" or "codex". Changing it starts the pixie's next
  // chat afresh, and its model and effort go back to that engine's defaults unless sent.
  provider: string;
  // Null: the engine's default model (on Claude, the agent defaults' model).
  model: string | null;
  effort: Effort | null;
  permission_mode: PermissionMode;
  autonomy: Autonomy;
  project_access: ProjectAccess;
  skills: string[];
  can_call: string[];
  hidden: boolean;
  // Chats it started that may run or wait at once (1 to 20), and start per local day (1 to 100).
  max_running: number;
  max_per_day: number;
}

export interface Pixie extends PixieSettings {
  id: string;
  slug: string;
  position: number;
  chat_session_id: string | null;
  // The team it belongs to, if any; one team per pixie (B40).
  team_id: string | null;
  // Its reports of severity "action" not read yet (B42).
  unread_action_reports: number;
  created_at: string;
  updated_at: string;
}

export type CallState = "running" | "done" | "failed" | "interrupted";

/** A call to a pixie in a chat (B46): its Agent call, or a SendMessage that continued it. */
export interface CallEntry {
  id: string;
  pixie_id: string;
  tool_use_id: string;
  agent_id: string | null;
  state: CallState;
  // It continued an earlier call's agent with its context.
  continued: boolean;
  started_at: string;
  finished_at: string | null;
}

export interface TeamMember {
  pixie_id: string;
  leader: boolean;
  // Its latest call's state with the team; null when it was not called yet.
  state: CallState | null;
}

/**
 * A solo pixie or a team a chat called and did not send away (B46), in the order first
 * called; `state` is its latest call's, and its calls are newest first.
 */
export interface GroupEntry {
  kind: "pixie" | "team";
  pixie_id: string | null;
  team_id: string | null;
  state: CallState;
  members: TeamMember[];
  calls: CallEntry[];
}

/** A subagent's own message, as stored in its chat. */
export interface AgentMessage {
  event_id: number;
  ts: string;
  blocks: JsonValue[];
}

/** A call with what it was asked, the agent's own messages and its report (B46). */
export interface CallWork extends CallEntry {
  prompt: string | null;
  messages: AgentMessage[];
  report: string | null;
}

/** A subagent's transcript so far, by its Agent call (B46). */
export interface AgentWork {
  tool_use_id: string;
  prompt: string | null;
  messages: AgentMessage[];
  report: string | null;
}

export type SendAwayBody = { pixie_id: string } | { team_id: string };

/** A team of pixies, called with `@handle`. Its members are the pixies naming it. */
export interface PixieTeam {
  id: string;
  name: string;
  // Shares the slug rules and namespace with pixie slugs.
  handle: string;
  // Always a member while the team has any; null when it has none.
  leader_id: string | null;
  position: number;
  created_at: string;
  updated_at: string;
}

export interface CreateTeamBody {
  name: string;
  handle?: string;
}

// `leader_id` must name a member (409 `leader_not_member` otherwise).
export interface UpdateTeamBody {
  name?: string;
  handle?: string;
  leader_id?: string;
}

export type CreatePixieBody = Partial<PixieSettings> & {
  name: string;
  slug?: string;
  soul?: string;
};
// Fields left out are unchanged; `team_id: null` leaves its team.
export type UpdatePixieBody = Partial<PixieSettings> & {
  slug?: string;
  team_id?: string | null;
};

/** A pixie file's text and the hash a later write must name. */
export interface PixieFile {
  text: string;
  hash: string;
}

/** A line of a pixie's memory that matched a search. */
export interface PixieSearchHit {
  file: string;
  line: string;
}

/** A changing call a pixie made in a chat (B41). */
export interface PixieActivity {
  id: number;
  ts: string;
  // The Nest tool, such as "send_message" or "start_session".
  tool: string;
  session_id: string | null;
  summary: string;
}

export type ReportSeverity = "info" | "warn" | "action";

/** What a pixie reported, from its chat or a habit run (B42). */
export interface PixieReport {
  id: string;
  pixie_id: string;
  severity: ReportSeverity;
  title: string;
  body: string;
  link: string | null;
  habit_id: string | null;
  run_id: string | null;
  created_at: string;
  read_at: string | null;
}

/** When a habit runs, in the Mac's local time; weekday 0 is Monday. */
export type HabitSchedule =
  | { kind: "hourly"; minute: number }
  | { kind: "daily"; time: string }
  | { kind: "weekdays"; time: string }
  | { kind: "weekly"; weekday: number; time: string };

export type HabitTrigger = "stuck" | "failed" | "review_ready" | "ci_failed";

export type HabitOutcome =
  "queued" | "running" | "reported" | "quiet" | "failed" | "stalled" | "timed_out" | "skipped";

export interface HabitRun {
  id: string;
  habit_id: string;
  pixie_id: string;
  // The run's own chat, read only.
  session_id: string | null;
  due_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  outcome: HabitOutcome;
  // Such as "usage" or "late" for a skipped run.
  reason: string | null;
  report_title: string | null;
}

/** A recurring or triggered task a pixie runs in a fresh background chat (B42). */
export interface Habit {
  id: string;
  pixie_id: string;
  name: string;
  prompt: string;
  schedule: HabitSchedule | null;
  triggers: HabitTrigger[];
  max_minutes: number;
  enabled: boolean;
  created_at: string;
  updated_at: string;
  next_due_at: string | null;
  last_run: HabitRun | null;
}

// A habit needs a schedule or at least one trigger (422 otherwise).
export interface HabitBody {
  name: string;
  prompt: string;
  schedule?: HabitSchedule | null;
  triggers?: HabitTrigger[];
  max_minutes?: number;
  enabled?: boolean;
}

export type UpdateHabitBody = Partial<HabitBody>;

/** The daemon's answer to /api/health. */
export interface Health {
  status: "ok";
  version: string;
  // The daemon machine's name for people (B105); absent from older daemons.
  machine?: string;
}

/** What the Mac's data folder holds (`GET /api/storage`, D104). */
export interface StorageUsage {
  total_bytes: number;
  chats_bytes: number;
  attachments_bytes: number;
  artifacts_bytes: number;
  other_bytes: number;
}

/** The [storage] section; null never archives (D104). */
export interface StorageSettings {
  archive_after_days: number | null;
}

/** A stored attachment, largest first (`GET /api/storage/attachments`). */
export interface StoredAttachment {
  id: string;
  name: string;
  bytes: number;
  media_type: string;
  session_id: string | null;
  session_title: string | null;
  created_at: string;
}

/** The [usage] section; PUT sends it back whole. */
export interface UsageSettings {
  // 0 turns the refresh off.
  refresh_minutes: number;
  // 50 to 99; null turns the warning off (D104).
  warn_percent: number | null;
  warn_notify: boolean;
}

/** The [stuck] thresholds (D036); 0 turns a check off. */
export interface StuckSettings {
  waiting_minutes: number;
  silent_minutes: number;
  repeated_calls: number;
  turn_minutes: number;
}

/** What new pixies start with, and the habit switches (`/api/pixie-settings`, D104). */
export interface PixieDefaults {
  model: string | null;
  autonomy: Autonomy;
  project_access: ProjectAccess;
  max_running: number;
  max_per_day: number;
  habits_paused: boolean;
  // Habit runs are skipped above this share of the 5 hour limit (50 to 100).
  habit_usage_percent: number;
}

export type GithubState = "signed_in" | "signed_out" | "unavailable";

/** The user's `gh` login as the Mac sees it; never a token. */
export interface GithubAccount {
  state: GithubState;
  login: string | null;
  checked_at: string;
}

/** Claude Code's own login on the Mac (`claude auth status`); never a token. */
export interface ClaudeAccount {
  signed_in: boolean;
  email: string | null;
  organization: string | null;
  plan: string | null;
  method: string | null;
  checked_at: string;
  // On an `account.claude` event: why the sign-in failed, else null.
  error?: string | null;
}

export interface PairingCode {
  code: string;
  expires_at: string;
}

/** A usage window that reached the warning level (`usage.warning`, D104). */
export interface UsageWarning {
  window: "five_hour" | "seven_day";
  utilization: number;
  resets_at: string | null;
}

export type ArtifactKind = "markdown" | "html" | "slides" | "document" | "design" | "design_system";

// Who saved a version: the agent, or the user editing a document in place (B88).
export type ArtifactAuthor = "agent" | "user";

/** A document a chat's agent saved (B79); every update adds a version. */
export interface Artifact {
  id: string;
  title: string;
  kind: ArtifactKind;
  // The saving chat's project, or "pixie:<id>" for a pixie's chat or habit run.
  repo: string;
  session_id: string | null;
  // The chat's current title, or its last one once deleted.
  chat_title: string | null;
  chat_deleted: boolean;
  pixie_id: string | null;
  pixie_name: string | null;
  created_at: string;
  // When the latest version was saved; lists are newest first by it.
  updated_at: string;
  latest_version: number;
  version_count: number;
  // The user opened the latest version.
  seen: boolean;
}

/** An installed Claude Code plugin (`GET /api/extensions/plugins`, D104). */
export interface InstalledPlugin {
  // "name@marketplace".
  id: string;
  name: string;
  marketplace: string;
  version: string | null;
  enabled: boolean;
  scope: "user" | "project" | "local";
  description: string | null;
}

/**
 * A skill a pixie may be given (B85): standalone and plugin skills, sorted by name. `name`
 * is what goes into the pixie's `skills`; a plugin's skill is "plugin:skill".
 */
export interface PixieSkill {
  name: string;
  description: string | null;
  plugin: string | null;
}

export interface Marketplace {
  name: string;
  // The CLI's source kind: "github", "git", "url", "directory"...
  kind: string;
  source: string | null;
}

/** A plugin a configured marketplace offers. */
export interface AvailablePlugin {
  id: string;
  name: string;
  marketplace: string;
  description: string | null;
  version: string | null;
  source: string;
  install_count: number | null;
  installed: boolean;
}

export interface PluginComponent {
  count: number;
  names: string[];
}

/** What a plugin brings; `components` is null when its files are not on the Mac yet. */
export interface PluginDetails {
  id: string;
  name: string;
  marketplace: string;
  description: string | null;
  source: string;
  installed: boolean;
  components: {
    skills: PluginComponent;
    agents: PluginComponent;
    hooks: PluginComponent;
    mcp_servers: PluginComponent;
    lsp_servers: PluginComponent;
  } | null;
}

export interface ArtifactVersion {
  version: number;
  title: string;
  size: number;
  created_at: string;
  author: ArtifactAuthor;
}

export interface ArtifactDetail extends Artifact {
  // Oldest first.
  versions: ArtifactVersion[];
}

export interface ArtifactContent {
  artifact_id: string;
  version: number;
  kind: ArtifactKind;
  title: string;
  content: string;
  // The whole document the sandboxed frame shows: the page itself for HTML, and for the
  // other kinds a page that renders the content.
  page: string;
  size: number;
  created_at: string;
  author: ArtifactAuthor;
  // An html page's other files (B88), built into `page`; none for the other kinds.
  files: ArtifactFile[];
}

export interface ArtifactFile {
  path: string;
  size: number;
  mime: string;
}

/** What an artifact's pages stored (B88), shared by all its versions. */
export interface ArtifactStorage {
  items: Record<string, string>;
  size: number;
}

/** Keys to set and to remove, applied together. */
export interface ArtifactStorageWrite {
  set: Record<string, string>;
  remove: string[];
}

/** A change to an artifact's stored data (`artifact.storage`); a clear comes first. */
export interface ArtifactStorageChange extends ArtifactStorageWrite {
  artifact_id: string;
  clear: boolean;
}

/** Claude's answer to a page's question (B88), and the asks left today. */
export interface ArtifactAnswer {
  text: string;
  remaining: number;
  // The daily limit, when the Mac says it.
  limit?: number;
}

/** Today's asks of an artifact's pages (B88), by the Mac's local day. */
export interface AskStatus {
  used: number;
  limit: number;
  remaining: number;
  resets_at: string | null;
  // Asking is on in the Mac's settings.
  enabled: boolean;
}

/** Usage as a page reads it (B88): the Usage page's numbers, nothing else. */
export interface PageUsage {
  limits: {
    five_hour: { utilization: number; resets_at: string | null } | null;
    seven_day: { utilization: number; resets_at: string | null } | null;
  };
  today: { tokens: number; sessions: number };
  week: { tokens: number; sessions: number };
}

/** Which artifacts a list shows; the filters combine, none means every project. */
export interface ArtifactFilter {
  repo?: string;
  session_id?: string;
  pixie_id?: string;
}

// Settings > Configuration (B97): what the engines share and each engine's own setup.

export type EngineId = "claude" | "codex";
export type SharedItem = "instructions" | "skills" | "mcp_servers";
export type SkillSource = "yours" | "synced" | "plugin" | "engine_only" | "project";
export type ConfigItemKind =
  | "plugins"
  | "connectors"
  | "hooks"
  | "subagents"
  | "commands"
  | "permissions"
  | "settings"
  | "rules";
export type McpTransport = "stdio" | "http" | "sse";

export interface InstructionsFile {
  path: string;
  exists: boolean;
  version: string | null;
}

export interface SkillItem {
  name: string;
  description: string | null;
  // Its SKILL.md.
  path: string;
  source: SkillSource;
  plugin: string | null;
  // The engine an `engine_only` skill is in.
  engine: EngineId | null;
  read_only: boolean;
  // Whether Codex loads it; null when Codex is not shown or cannot see it at all.
  codex_enabled: boolean | null;
  // Why Codex cannot load it.
  codex_error: string | null;
}

export interface SharedServer {
  name: string;
  summary: string;
  transport: McpTransport;
  engines: EngineId[];
  convertible: boolean;
  reason: string | null;
}

export interface ConfigSwitch {
  on: boolean;
  fixed: boolean;
}

export interface EngineItem {
  kind: ConfigItemKind;
  count: number | null;
  detail: string | null;
  path: string | null;
  folder: boolean;
}

export interface EngineSection {
  id: EngineId;
  name: string;
  // Such as "me@example.com · Claude Max"; null when unknown.
  account: string | null;
  bundled_version: string | null;
  standalone: { path: string; version: string | null } | null;
  config_folder: string;
  uses_shared: Record<SharedItem, ConfigSwitch>;
  missing_from_shared: { instructions: boolean; skills: string[]; mcp_servers: string[] };
  items: EngineItem[];
}

/** `GET /api/configuration`; the writes answer with it too. */
export interface ConfigurationPage {
  shared: {
    instructions: InstructionsFile;
    skills: { folder: string; items: SkillItem[] };
    mcp_servers: SharedServer[];
  };
  engines: EngineSection[];
}

/** A setup file's text; `version` (its hash) is null when there is no file yet. */
export interface FileText {
  path: string;
  text: string;
  version: string | null;
}

/** A server as Claude keeps it: the edit form and `PUT .../mcp-servers/{name}`. */
export interface McpServer {
  transport: McpTransport;
  command?: string | null;
  args?: string[];
  env?: Record<string, string>;
  url?: string | null;
  headers?: Record<string, string>;
}

export interface McpServerSummary {
  name: string;
  summary: string;
  transport: McpTransport;
}

/** What "Copy <engine>'s setup to Shared" would do, for its popup. */
export interface CopyPreview {
  // Null when the shared instructions stay as they are.
  instructions: { replace: boolean; engine_path: string; shared_path: string } | null;
  skills: { add: string[]; already: string[]; same_name: { name: string; reason: string }[] };
  mcp_servers: {
    add: string[];
    already: string[];
    not_convertible: { name: string; reason: string }[];
  };
  // What stays with the engine, as lines.
  stays: string[];
}

export interface CopyResult {
  // The done line.
  summary: string;
  undo_id: string;
  page: ConfigurationPage;
}

/** A project's own instructions, skills and MCP servers (Settings > Project). */
export interface ProjectConfiguration {
  instructions: { path: string; exists: boolean }[];
  skills: SkillItem[];
  mcp_servers: McpServerSummary[];
}

export interface CodexPlugin {
  id: string;
  name: string;
  marketplace: string;
  description: string | null;
  version: string | null;
  installed: boolean;
  enabled: boolean;
}

export interface CodexMarketplace {
  name: string;
  path: string | null;
}

/** Every plugin of Codex's marketplaces, installed first. */
export interface CodexPlugins {
  plugins: CodexPlugin[];
  marketplaces: CodexMarketplace[];
}

/** One entry of Settings > Features (B103): what makes Nest different. */
export interface Feature {
  id: string;
  name: string;
  // Plain sentences; `backticks` spans show as code.
  text: string;
  // Where to find it in the app.
  where: string;
  // YYYY-MM-DD.
  added: string;
  changed: string | null;
  block: string;
  // New on this device: recent, and not shown yet or first shown less than a day ago.
  new: boolean;
}

export interface FeatureGroup {
  id: string;
  name: string;
  features: Feature[];
}

/** GET /api/features, and what POST /api/features/seen answers. */
export interface FeaturesCatalog {
  groups: FeatureGroup[];
  new_count: number;
}
