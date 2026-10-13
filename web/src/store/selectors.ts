import type {
  Approval,
  BackgroundSummary,
  ClaudeChat,
  HarnessEvent,
  PrStatus,
  Session,
  StuckFlag,
} from "../api/types.ts";
import { list, obj, str } from "../api/payloads.ts";
import type { State } from "./state.ts";

export type Tone = "run" | "wait" | "rev" | "fail" | "done" | "idle" | "int";

export interface ChatStatus {
  tone: Tone;
  label: string;
}

export function pendingFor(state: State, sessionId: string): Approval[] {
  return Object.values(state.approvals)
    .filter((a) => a.session_id === sessionId)
    .sort((a, b) => a.created_at.localeCompare(b.created_at));
}

export function chatStatus(session: Session, pending: Approval[]): ChatStatus {
  const kinds = new Set(pending.map((a) => a.kind));
  if (kinds.has("question")) return { tone: "wait", label: "Question" };
  if (kinds.has("plan")) return { tone: "wait", label: "Plan ready" };
  if (kinds.has("permission") || session.state === "waiting") {
    return { tone: "wait", label: "Needs approval" };
  }
  switch (session.state) {
    case "starting":
      return { tone: "run", label: "Starting" };
    case "running":
      return { tone: "run", label: "Running" };
    case "failed":
      return { tone: "fail", label: "Failed" };
    case "interrupted":
      return { tone: "int", label: "Interrupted" };
    case "closed":
      return { tone: "done", label: "Done" };
    default:
      if (kinds.has("review")) return { tone: "rev", label: "Ready for review" };
      return kinds.has("merge")
        ? { tone: "rev", label: "Ready to merge" }
        : { tone: "idle", label: "Idle" };
  }
}

export type ChatGroup = "pinned" | "need" | "run" | "idle" | "done";

// The order the groups are listed in.
export const GROUP_ORDER: ChatGroup[] = ["pinned", "need", "run", "idle", "done"];

export const GROUP_LABELS: Record<ChatGroup, string> = {
  pinned: "Pinned",
  need: "Needs you",
  run: "Running",
  idle: "Idle",
  done: "Done",
};

export function chatGroup(session: Session, status: ChatStatus): ChatGroup {
  if (session.pinned) return "pinned";
  // A stuck chat needs the user like a prompt does (D036).
  if (status.tone === "wait" || status.tone === "rev" || session.stuck !== null) return "need";
  if (status.tone === "run") return "run";
  if (status.tone === "done") return "done";
  return "idle";
}

/** A harness session, or a Claude Code chat harness can continue (always idle). */
export type ChatEntry =
  | { session: Session; chat?: undefined; status: ChatStatus }
  | { chat: ClaudeChat; session?: undefined; status: ChatStatus };

export const CLAUDE_CHAT_STATUS: ChatStatus = { tone: "idle", label: "Claude Code" };

function entryTime(entry: ChatEntry): string {
  return entry.session === undefined ? entry.chat.last_activity_at : entry.session.updated_at;
}

function archived(entry: ChatEntry): boolean {
  return entry.session === undefined ? entry.chat.archived : entry.session.archived_at !== null;
}

export interface ChatLists {
  groups: { group: ChatGroup; chats: ChatEntry[] }[];
  archived: ChatEntry[];
}

/**
 * A project's chats: pinned first, then by what they need, newest first in each group.
 * Claude Code chats join the idle group; archived ones of both kinds are listed apart.
 */
export function chatLists(state: State, repo: string): ChatLists {
  const sessions: ChatEntry[] = Object.values(state.sessions)
    .filter((s) => s.repo === repo)
    .map((session) => ({ session, status: chatStatus(session, pendingFor(state, session.id)) }));
  const chats: ChatEntry[] = Object.values(state.claudeChats)
    .filter((c) => c.repo === repo)
    .map((chat) => ({ chat, status: CLAUDE_CHAT_STATUS }));
  const entries = [...sessions, ...chats].sort((a, b) => entryTime(b).localeCompare(entryTime(a)));
  const groupOf = (e: ChatEntry): ChatGroup =>
    e.session === undefined ? "idle" : chatGroup(e.session, e.status);
  const live = entries.filter((e) => !archived(e));
  return {
    groups: GROUP_ORDER.map((group) => ({
      group,
      chats: live.filter((e) => groupOf(e) === group),
    })).filter((g) => g.chats.length > 0),
    archived: entries.filter(archived),
  };
}

export interface InboxGroup {
  repo: string;
  items: Approval[];
  // Open pull requests whose checks failed, for "Send to agent".
  failures: CiFailure[];
  // Chats that look stuck, for Interrupt and "Send a nudge".
  stuck: StuckChat[];
}

export interface StuckChat {
  repo: string;
  session: Session;
  stuck: StuckFlag;
}

export interface CiFailure {
  repo: string;
  session: Session;
  pr: PrStatus;
  // The failing checks' names.
  names: string[];
}

const BUSY: Session["state"][] = ["starting", "running", "waiting", "closed"];

/**
 * The names of the failing checks when the session's open pull request failed and the
 * agent could take a fix: it is not working on one, and no review of new work is waiting.
 */
export function ciFailure(session: Session, pending: Approval[]): CiFailure | null {
  const pr = session.pr;
  if (pr?.state !== "open" || pr.checks.state !== "failure") return null;
  if (BUSY.includes(session.state) || session.archived_at !== null) return null;
  if (pending.some((a) => a.kind === "review")) return null;
  const names = pr.checks.items.filter((c) => c.state === "failure").map((c) => c.name);
  return { repo: session.repo, session, pr, names };
}

function failures(state: State): CiFailure[] {
  return Object.values(state.sessions)
    .flatMap((s) => ciFailure(s, pendingFor(state, s.id)) ?? [])
    .sort((a, b) => a.pr.changed_at.localeCompare(b.pr.changed_at));
}

/** Chats flagged as stuck, the longest stuck first. */
export function stuckChats(state: State): StuckChat[] {
  return Object.values(state.sessions)
    .flatMap((session) =>
      session.stuck !== null && session.archived_at === null
        ? [{ repo: session.repo, session, stuck: session.stuck }]
        : [],
    )
    .sort((a, b) => a.stuck.since.localeCompare(b.stuck.since));
}

/** What a nudge to a stuck chat says, from the reason it looks stuck. */
export function nudgeText(details: string): string {
  const reason = details.replace(/\.$/, "");
  const lowered = reason.charAt(0).toLowerCase() + reason.slice(1);
  return `You seem stuck: ${lowered}. Step back and try a different approach.`;
}

/** Every pending item, failed check and stuck chat, by project in the order they are listed. */
export function inboxGroups(state: State): InboxGroup[] {
  const order = state.repos.map((r) => r.name);
  const rank = (repo: string) => (order.includes(repo) ? order.indexOf(repo) : order.length);
  const items = Object.values(state.approvals).sort((a, b) =>
    a.created_at.localeCompare(b.created_at),
  );
  const failed = failures(state);
  const stuck = stuckChats(state);
  const repos = [...new Set([...items, ...failed, ...stuck].map((x) => x.repo))].sort(
    (a, b) => rank(a) - rank(b) || a.localeCompare(b),
  );
  return repos.map((repo) => ({
    repo,
    items: items.filter((a) => a.repo === repo),
    failures: failed.filter((f) => f.repo === repo),
    stuck: stuck.filter((s) => s.repo === repo),
  }));
}

export function needsCount(state: State, repo?: string): number {
  const mine = (x: { repo: string }) => repo === undefined || x.repo === repo;
  return (
    Object.values(state.approvals).filter(mine).length +
    failures(state).filter(mine).length +
    stuckChats(state).filter(mine).length
  );
}

export function isRunning(state: State, repo: string): boolean {
  return Object.values(state.sessions).some(
    (s) => s.repo === repo && (s.state === "running" || s.state === "starting"),
  );
}

/** The event each tool call was made in, by tool use id. */
function callEvents(events: HarnessEvent[]): Map<string, number> {
  const calls = new Map<string, number>();
  for (const e of events) {
    if (e.type !== "session.message") continue;
    for (const block of list(e.payload.blocks).map(obj)) {
      const id = str(block.id);
      if (block.type === "tool_use" && id !== null) calls.set(id, Number(e.id));
    }
  }
  return calls;
}

/**
 * The background bar's tasks: those of the exchange the user's latest message opened,
 * plus any earlier one still at work, which counts as completed here once it finishes.
 * Turns the agent starts by itself stay in the exchange. Without a user message in the
 * transcript, every task counts. A task belongs to the exchange by the event that started
 * it, so a clock change cannot move it (I-H); one whose call is not in the transcript goes
 * by its start time. Finishing still goes by time, as no event records it.
 */
export function exchangeBackground(
  summary: BackgroundSummary,
  events: HarnessEvent[] | undefined,
): BackgroundSummary {
  const all = events ?? [];
  const message = all.findLast((e) => e.type === "session.user_message");
  if (message === undefined) return summary;
  const start = Date.parse(message.ts);
  const calls = callEvents(all);
  const since = (ts: string | null) => ts !== null && Date.parse(ts) >= start;
  const startedSince = (item: BackgroundSummary["items"][number]) => {
    const call = calls.get(item.id);
    return call === undefined ? since(item.started_at) : call > Number(message.id);
  };
  const items = summary.items.filter(
    (item) => item.status === "running" || startedSince(item) || since(item.finished_at),
  );
  const running = items.filter((item) => item.status === "running").length;
  return { running, completed: items.length - running, items };
}
