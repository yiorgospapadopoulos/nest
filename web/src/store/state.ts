import type {
  AccountInfo,
  AgentDefaults,
  Approval,
  Attachment,
  BackgroundSummary,
  ClaudeChat,
  Connector,
  HarnessEvent,
  ModelOption,
  NotificationSettings,
  QueuedMessage,
  RepoConfig,
  Session,
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

// A message being written: kept per chat (by session id) or per project for a new chat
// (see draftKey), so switching chats never carries it along.
export interface Draft {
  text: string;
  files: Attachment[];
}

export const NO_DRAFT: Draft = { text: "", files: [] };

/** Where a composer keeps its draft. */
export function draftKey(target: { session: string } | { repo: string }): string {
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
  // Claude Code chats of the projects that harness does not own, by Claude Code session id.
  claudeChats: Record<string, ClaudeChat>;
  // List chats programs started through an Agent SDK too; remembered on this device.
  showAutomated: boolean;
  // Pending items only.
  approvals: Record<string, Approval>;
  tracking: Record<string, Tracking>;
  // Stored events of the chats that were opened, oldest first.
  transcripts: Record<string, HarnessEvent[]>;
  history: Record<string, HistoryStatus>;
  // Assistant text streaming in before its message is complete.
  live: Record<string, string>;
  // When the agent started the thinking it is doing now (D045); live only.
  thinking: Record<string, string>;
  // Messages waiting for the running turn to end, oldest first.
  queued: Record<string, QueuedMessage[]>;
  drafts: Record<string, Draft>;
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
  claudeChats: {},
  showAutomated: false,
  approvals: {},
  tracking: {},
  transcripts: {},
  history: {},
  live: {},
  thinking: {},
  queued: {},
  drafts: {},
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
  | { type: "claudeChats"; chats: ClaudeChat[] }
  | { type: "claudeChat"; chat: ClaudeChat }
  | { type: "claudeChatRemoved"; id: string }
  | { type: "showAutomated"; on: boolean }
  | { type: "approval"; approval: Approval }
  | { type: "tracking"; id: string; tracking: Tracking }
  | { type: "transcriptOpened"; id: string }
  | { type: "transcriptLoaded"; id: string; events: HarnessEvent[] }
  | { type: "transcriptClosed"; id: string }
  | { type: "historyFailed"; id: string }
  | { type: "queued"; id: string; queued: QueuedMessage[] }
  | { type: "queuedRemoved"; id: string; queuedId: string }
  | { type: "event"; event: HarnessEvent }
  // Stored events applied again after a snapshot that may predate them.
  | { type: "replayed"; events: HarnessEvent[] }
  // Ephemeral output (streamed text, thinking) that a refetch made stale.
  | { type: "liveCleared"; id: string }
  | { type: "draftText"; key: string; text: string }
  | { type: "draftFileAdded"; key: string; file: Attachment }
  | { type: "draftFileRemoved"; key: string; fileId: string }
  // A message from the draft went out: what was typed or attached since stays.
  // `to`: the new chat the first message created, which takes what is left of the draft.
  | { type: "draftSent"; key: string; text: string; fileIds: string[]; to?: string }
  | { type: "connectors"; connectors: Connector[] }
  | { type: "limits"; limits: UsageLimits }
  | { type: "notifications"; notifications: NotificationSettings }
  | { type: "models"; models: ModelOption[] }
  | { type: "account"; account: AccountInfo }
  | { type: "agentDefaults"; defaults: AgentDefaults }
  | { type: "toast"; toast: Toast | null };
