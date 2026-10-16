import type {
  AccountInfo,
  AgentDefaults,
  Approval,
  Attachment,
  BackgroundSummary,
  ClaudeChat,
  Connector,
  Goal,
  GroupEntry,
  Habit,
  HabitRun,
  NestEvent,
  ModelOption,
  NotificationSettings,
  Pixie,
  PixieReport,
  PixieTeam,
  QueuedMessage,
  RepoConfig,
  Session,
  ShellResult,
  TrackedAgent,
  TrackedTask,
  UsageLimits,
} from "../api/types.ts";

export type AuthState = "loading" | "ready" | "unpaired" | "forbidden" | "offline";

export interface Tracking {
  tasks: TrackedTask[];
  agents: TrackedAgent[];
  background: BackgroundSummary;
}

export const NO_BACKGROUND: BackgroundSummary = { running: 0, completed: 0, items: [] };

/**
 * A `!` command run in a chat (B59): running until it has a result or an error. Kept on
 * this device only, like a draft, until a message gives Claude what ran.
 */
export interface BashRun {
  id: number;
  command: string;
  result: ShellResult | null;
  error: string | null;
}

// A message being written: kept per chat (by session id) or per project for a new chat
// (see draftKey), so switching chats never carries it along.
export interface Draft {
  text: string;
  files: Attachment[];
}

export const NO_DRAFT: Draft = { text: "", files: [] };

/** Where a composer keeps its draft. */
export function draftKey(
  target: { session: string } | { repo: string } | { pixie: string },
): string {
  if ("pixie" in target) return `pixie:${target.pixie}`;
  return "session" in target ? `session:${target.session}` : `new:${target.repo}`;
}

// Whether an open chat's history arrived; a failed load is tried again (BUG-66).
export type HistoryStatus = "loading" | "loaded" | "failed";

export interface Toast {
  id: number;
  text: string;
  tone: "ok" | "error" | "info";
}

export interface State {
  auth: AuthState;
  // The event socket dropped and is reconnecting.
  reconnecting: boolean;
  repos: RepoConfig[];
  sessions: Record<string, Session>;
  // The user's pixies by id; their chats are sessions with a pixie_id.
  pixies: Record<string, Pixie>;
  // Teams of pixies by id (B40).
  teams: Record<string, PixieTeam>;
  // The pixies' reports by id, the latest the Mac keeps (B42).
  reports: Record<string, PixieReport>;
  // Each pixie's habits, by pixie id, once its list was asked for.
  habits: Record<string, Habit[]>;
  // A habit's runs, newest first, by habit id, while its history was asked for.
  habitRuns: Record<string, HabitRun[]>;
  // The teams folded in the pixie list; remembered on this device.
  foldedTeams: string[];
  // Claude Code chats of the projects that Nest does not own, by Claude Code session id.
  claudeChats: Record<string, ClaudeChat>;
  // List chats programs started through an Agent SDK too; remembered on this device.
  showAutomated: boolean;
  // Pending items only.
  approvals: Record<string, Approval>;
  tracking: Record<string, Tracking>;
  // Each project chat's pixies and teams (B46), by session id; chats without any are left out.
  pixieGroups: Record<string, GroupEntry[]>;
  // Stored events of the chats that were opened, oldest first.
  transcripts: Record<string, NestEvent[]>;
  history: Record<string, HistoryStatus>;
  // Assistant text streaming in before its message is complete.
  live: Record<string, string>;
  // When the agent started the thinking it is doing now (D045); live only.
  thinking: Record<string, string>;
  // That thinking's text as it streams in, until its block arrives (B59).
  thoughts: Record<string, string>;
  // Subagents' text as it streams in, per chat by the id of the Agent call (B59).
  agentLive: Record<string, Record<string, string>>;
  // Messages sent while a turn runs that Claude has not read yet, oldest first (B59).
  queued: Record<string, QueuedMessage[]>;
  drafts: Record<string, Draft>;
  // Each chat's `!` commands since its last message, oldest first (B59).
  bash: Record<string, BashRun[]>;
  connectors: Connector[] | null;
  limits: UsageLimits | null;
  // The daemon's notification rules, once the Account tab asked for them.
  notifications: NotificationSettings | null;
  // Claude Code's models in its order, once asked for.
  models: ModelOption[] | null;
  account: AccountInfo | null;
  agentDefaults: AgentDefaults | null;
  toast: Toast | null;
}

export const initialState: State = {
  auth: "loading",
  reconnecting: false,
  repos: [],
  sessions: {},
  pixies: {},
  teams: {},
  reports: {},
  habits: {},
  habitRuns: {},
  foldedTeams: [],
  claudeChats: {},
  showAutomated: false,
  approvals: {},
  tracking: {},
  pixieGroups: {},
  transcripts: {},
  history: {},
  live: {},
  thinking: {},
  thoughts: {},
  agentLive: {},
  queued: {},
  drafts: {},
  bash: {},
  connectors: null,
  limits: null,
  notifications: null,
  models: null,
  account: null,
  agentDefaults: null,
  toast: null,
};

export type Action =
  | { type: "auth"; auth: AuthState }
  | { type: "reconnecting"; on: boolean }
  | { type: "loaded"; repos: RepoConfig[]; sessions: Session[]; approvals: Approval[] }
  | { type: "repo"; repo: RepoConfig }
  | { type: "repoRemoved"; name: string }
  | { type: "session"; session: Session }
  | { type: "sessionRemoved"; id: string }
  | { type: "pixies"; pixies: Pixie[] }
  | { type: "pixie"; pixie: Pixie }
  | { type: "pixieRemoved"; id: string }
  | { type: "teams"; teams: PixieTeam[] }
  | { type: "team"; team: PixieTeam }
  | { type: "teamRemoved"; id: string }
  | { type: "teamFolded"; id: string; folded: boolean }
  | { type: "reports"; reports: PixieReport[] }
  | { type: "report"; report: PixieReport }
  | { type: "reportsRead"; ids: string[]; at: string }
  | { type: "habits"; pixieId: string; habits: Habit[] }
  | { type: "habit"; habit: Habit }
  | { type: "habitRemoved"; pixieId: string; id: string }
  | { type: "habitRuns"; habitId: string; runs: HabitRun[] }
  | { type: "habitRun"; run: HabitRun }
  | { type: "claudeChats"; chats: ClaudeChat[] }
  | { type: "claudeChat"; chat: ClaudeChat }
  | { type: "claudeChatRemoved"; id: string }
  | { type: "showAutomated"; on: boolean }
  | { type: "approval"; approval: Approval }
  | { type: "tracking"; id: string; tracking: Tracking }
  // A project's goals (B47): the steps of its chats that have any, all the others none.
  | { type: "goals"; repo: string; goals: Goal[] }
  | { type: "pixieGroups"; groups: Record<string, GroupEntry[]> }
  | { type: "pixieGroup"; id: string; group: GroupEntry[] }
  | { type: "transcriptOpened"; id: string }
  | { type: "transcriptLoaded"; id: string; events: NestEvent[] }
  | { type: "transcriptClosed"; id: string }
  | { type: "historyFailed"; id: string }
  | { type: "queued"; id: string; queued: QueuedMessage[] }
  | { type: "queuedRemoved"; id: string; queuedId: string }
  | { type: "event"; event: NestEvent }
  // Stored events applied again after a snapshot that may predate them.
  | { type: "replayed"; events: NestEvent[] }
  // Ephemeral output (streamed text, thinking) that a refetch made stale.
  | { type: "liveCleared"; id: string }
  | { type: "draftText"; key: string; text: string }
  | { type: "draftFileAdded"; key: string; file: Attachment }
  | { type: "draftFileRemoved"; key: string; fileId: string }
  // A message taken back (a pending one edited, a rewind, a fork) put in the draft.
  | { type: "draftFilled"; key: string; text: string; files: Attachment[] }
  // A message from the draft went out: what was typed or attached since stays.
  // `to`: the new chat the first message created, which takes what is left of the draft.
  | { type: "draftSent"; key: string; text: string; fileIds: string[]; to?: string }
  | { type: "bashStarted"; id: string; runId: number; command: string }
  | { type: "bashFinished"; id: string; runId: number; result?: ShellResult; error?: string }
  // A message carried these runs to Claude, or they ended in an error before it.
  | { type: "bashSent"; id: string; runIds: number[] }
  | { type: "connectors"; connectors: Connector[] }
  | { type: "limits"; limits: UsageLimits }
  | { type: "notifications"; notifications: NotificationSettings }
  | { type: "models"; models: ModelOption[] }
  | { type: "account"; account: AccountInfo }
  | { type: "agentDefaults"; defaults: AgentDefaults }
  | { type: "toast"; toast: Toast | null };
