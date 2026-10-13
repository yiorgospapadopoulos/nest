// The daemon's JSON shapes (daemon/src/harness/**/models.py), field for field.

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
  git_violation: boolean;
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
  // Up to three lines about the pull request harness opened.
  pr_summary: string | null;
  // Set while the chat looks stuck.
  stuck: StuckFlag | null;
}

/** A Claude Code chat of a registered repo that harness does not own (D028). */
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
  // Archived in harness only (D040); listed with the archived chats.
  archived: boolean;
}

export interface TrackedTask {
  id: string;
  subject: string;
  description: string | null;
  active_form: string | null;
  status: "pending" | "in_progress" | "completed" | "deleted";
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

/** A message sent while a turn runs; the next turn that ends normally delivers it. */
export interface QueuedMessage {
  id: string;
  text: string;
  attachments: QueuedAttachment[];
  created_at: string;
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

export type ApprovalKind = "permission" | "question" | "review" | "plan" | "merge";
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

// The commit and branch a publish would use; null when HEAD is detached or unborn.
export interface ReviewHead {
  commit: string | null;
  branch: string | null;
}

export interface ReviewCommit {
  sha: string;
  subject: string;
}

export interface SessionDiff {
  base: string | null;
  head: ReviewHead;
  // Commits on HEAD that neither the base nor harness's own publishing accounts for.
  commits: ReviewCommit[];
  files: FileDiff[];
  stats: DiffStats;
}

export interface DayUsage {
  date: string;
  tokens: number;
  sessions: number;
}

export interface TokenTotals {
  input_tokens: number;
  output_tokens: number;
  cache_creation_input_tokens: number;
  cache_read_input_tokens: number;
  total: number;
}

export interface MonthUsage {
  year: number;
  month: number;
  sessions: number;
  tokens: TokenTotals;
  days: DayUsage[];
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

export interface HarnessEvent {
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
  model?: string;
  effort?: Effort;
  permission_mode?: PermissionMode;
  attachment_ids?: string[];
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
  // The user checked the git refs the agent changed itself (session.git_violation).
  acknowledge_violation?: boolean;
  // The HEAD the user reviewed; the daemon refuses with `head_changed` if it moved.
  expected_head?: string;
  // The push address the user confirmed after a `remote_not_confirmed` or `remote_changed`.
  confirm_remote_url?: string;
}

/** What restoring files to before a message would do (`GET .../rewind?message=`). */
export interface RewindPreview {
  can_rewind: boolean;
  // The paths, or only how many (the SDK reports paths; a count is accepted too).
  files_changed: string[] | number;
  insertions: number;
  deletions: number;
  // Why the files cannot be restored, when they cannot.
  error: string | null;
}

/** A project's links and setup commands (`PATCH /api/repos/{name}`). */
export interface RepoPatch {
  link?: string[];
  setup?: string[];
}

export type NotifyKind =
  | "needs_approval"
  | "question"
  | "review_ready"
  | "failed"
  | "finished"
  | "ci_failed"
  | "ready_to_merge"
  | "stuck";

export type SearchHitKind = "title" | "user" | "assistant" | "tool" | "tool_result" | "claude_chat";

/** A chat title or message matching a search (D035). */
export interface SearchHit {
  // A harness session, or a Claude Code chat id for kind "claude_chat".
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
  // The thinking level Claude Code's own settings give it, when they set one.
  claude_code_effort: string | null;
}

export interface ModelList {
  models: ModelOption[];
  // Null while the Mac has only Claude Code's aliases to offer.
  updated_at: string | null;
}

/** Who Claude Code is signed in as; every field may be unknown. */
export interface AccountInfo {
  display_name: string | null;
  email: string | null;
  plan: string | null;
  organization: string | null;
}

/** What new chats use unless the composer chooses otherwise (`/api/agents/defaults`). */
export interface AgentDefaults {
  // Null leaves the choice to Claude Code.
  model: string | null;
  effort: Effort | null;
  // Null leaves it to Claude Code's own setting (its `defaultMode`).
  permission_mode: PermissionMode | null;
  mode: SessionMode;
}
