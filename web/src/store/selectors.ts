import type {
  Approval,
  BackgroundSummary,
  ClaudeChat,
  GroupEntry,
  NestEvent,
  Pixie,
  PixieReport,
  PixieTeam,
  PrStatus,
  Session,
  StuckFlag,
  TrackedAgent,
  TrackedTask,
} from "../api/types.ts";
import { list, obj, str } from "../api/payloads.ts";
import type { State } from "./state.ts";

// A pixie chat's repo, under which its inbox items group (D072).
const PIXIE_REPO = "pixie:";

export type Tone = "run" | "wait" | "rev" | "fail" | "done" | "idle" | "int";

export interface ChatStatus {
  tone: Tone;
  label: string;
}

/** A pixie's chat lives in its own screen, never in a project's lists. */
function projectChats(state: State): Session[] {
  return Object.values(state.sessions).filter((s) => s.pixie_id == null);
}

/** The pixies shown in the app, in the order the user set; hidden ones only on request. */
export function pixieList(state: State, withHidden = false): Pixie[] {
  return Object.values(state.pixies)
    .filter((p) => withHidden || !p.hidden)
    .sort((a, b) => a.position - b.position);
}

/** The teams in the order the user set. */
export function teamList(state: State): PixieTeam[] {
  return Object.values(state.teams).sort((a, b) => a.position - b.position);
}

/**
 * The pixies a project chat can call, in list order: every one not hidden and with access
 * to project files, in every project (B85).
 */
export function availablePixies(state: State): Pixie[] {
  return pixieList(state).filter((p) => p.project_access !== "none");
}

export interface CallableTeam {
  team: PixieTeam;
  // Its members the chat can call, in list order; the leader is one of them.
  members: Pixie[];
}

/** The teams a project chat can call: those whose leader it can call. */
export function availableTeams(state: State): CallableTeam[] {
  const available = availablePixies(state);
  return teamList(state).flatMap((team) =>
    available.some((p) => p.id === team.leader_id)
      ? [{ team, members: available.filter((p) => p.team_id === team.id) }]
      : [],
  );
}

/**
 * The pixies a project chat can call on their own (B46): those in no team it can call,
 * since a team's pixies are called only with their team.
 */
export function soloPixies(state: State): Pixie[] {
  const teams = new Set(availableTeams(state).map(({ team }) => team.id));
  return availablePixies(state).filter((p) => p.team_id === null || !teams.has(p.team_id));
}

// A whole @ token, as the daemon finds pixie slugs.
const MENTION = /(?<=^|\s)@[a-z0-9-]+(?![\w-])/g;

/**
 * Why `text` cannot be sent from a project chat: it calls a pixie of a team the chat can
 * call on its own, as the daemon refuses it (B46); null when it can be sent.
 */
export function memberCall(state: State, text: string): string | null {
  const members = new Map(
    availableTeams(state).flatMap(({ team, members }) =>
      members.map((p) => [p.slug, `${p.name} is in @${team.handle}; call the team or a solo copy`]),
    ),
  );
  for (const match of text.matchAll(MENTION)) {
    const why = members.get(match[0].slice(1));
    if (why !== undefined) return why;
  }
  return null;
}

/** A running subagent with those it started, for a chat's tree (B46). */
export interface AgentNode {
  agent: TrackedAgent;
  children: AgentNode[];
}

export interface ChatTree {
  // The pixies and teams the chat called and did not send away.
  pixies: GroupEntry[];
  // Its running subagents that are not pixies, each under the subagent that started it.
  subagents: AgentNode[];
}

/** What a chat has working, for the tree under its row (B46). */
export function chatTree(state: State, sessionId: string): ChatTree {
  const pixies = state.pixieGroups[sessionId] ?? [];
  const calls = new Set(pixies.flatMap((entry) => entry.calls.map((c) => c.tool_use_id)));
  const slugs = new Set(Object.values(state.pixies).map((p) => p.slug));
  const running = (state.tracking[sessionId]?.agents ?? []).filter(
    (a) => a.id !== "main" && a.status === "running" && !calls.has(a.id) && !slugs.has(a.name),
  );
  const shown = new Set(running.map((a) => a.id));
  const nodes = (parent: string | null): AgentNode[] =>
    running
      .filter((a) => (a.parent != null && shown.has(a.parent) ? a.parent : null) === parent)
      .map((agent) => ({ agent, children: nodes(agent.id) }));
  return { pixies, subagents: nodes(null) };
}

/**
 * Whether a pixie is at work (B48): its own chat starts or runs, or a call of it runs in
 * any chat, alone or with its team.
 */
export function pixieWorking(state: State, pixie: Pixie): boolean {
  const own = pixie.chat_session_id === null ? undefined : state.sessions[pixie.chat_session_id];
  if (own?.state === "starting" || own?.state === "running") return true;
  return Object.values(state.pixieGroups).some((group) =>
    group.some((entry) =>
      entry.kind === "team"
        ? entry.members.some((m) => m.pixie_id === pixie.id && m.state === "running")
        : entry.pixie_id === pixie.id && entry.state === "running",
    ),
  );
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
      if (kinds.has("merge")) return { tone: "rev", label: "Ready to merge" };
      // Idle until a usage limit resets, then it goes on by itself (B78).
      return session.limit_pause === null
        ? { tone: "idle", label: "Idle" }
        : { tone: "int", label: "Paused" };
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

/** A Nest session, or a Claude Code chat Nest can continue (always idle). */
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
  const sessions: ChatEntry[] = projectChats(state)
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

/** A chat in a project's Goals section (B47) with the steps it shows. */
export interface GoalEntry {
  session: Session;
  status: ChatStatus;
  tasks: TrackedTask[];
}

const IN_FLIGHT = new Set<Session["state"]>(["starting", "running", "waiting"]);

/**
 * What the project's chats are working towards, as the daemon lists goals (D092): chats
 * at work, with or without steps, then chats with steps left showing; newest first in each.
 */
export function goalEntries(state: State, repo: string): GoalEntry[] {
  return projectChats(state)
    .filter((s) => s.repo === repo && s.archived_at === null)
    .map((session) => ({
      session,
      status: chatStatus(session, pendingFor(state, session.id)),
      tasks: (state.tracking[session.id]?.tasks ?? []).filter((t) => t.status !== "deleted"),
    }))
    .filter(({ session, tasks }) => IN_FLIGHT.has(session.state) || tasks.length > 0)
    .sort(
      (a, b) =>
        Number(IN_FLIGHT.has(b.session.state)) - Number(IN_FLIGHT.has(a.session.state)) ||
        b.session.updated_at.localeCompare(a.session.updated_at),
    );
}

export interface InboxGroup {
  repo: string;
  items: Approval[];
  // Open pull requests whose checks failed, for "Send to agent".
  failures: CiFailure[];
  // Chats that look stuck, for Interrupt and "Send a nudge".
  stuck: StuckChat[];
  // A pixie's unread warn and action reports, newest first (B42).
  reports: PixieReport[];
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
  return projectChats(state)
    .flatMap((s) => ciFailure(s, pendingFor(state, s.id)) ?? [])
    .sort((a, b) => a.pr.changed_at.localeCompare(b.pr.changed_at));
}

/** Chats flagged as stuck, the longest stuck first. */
export function stuckChats(state: State): StuckChat[] {
  return projectChats(state)
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
  const reports = inboxReports(state);
  const repos = [...new Set([...items, ...failed, ...stuck, ...reports].map((x) => x.repo))].sort(
    (a, b) => rank(a) - rank(b) || a.localeCompare(b),
  );
  return repos.map((repo) => ({
    repo,
    items: items.filter((a) => a.repo === repo),
    failures: failed.filter((f) => f.repo === repo),
    stuck: stuck.filter((s) => s.repo === repo),
    reports: reports.filter((r) => r.repo === repo).map((r) => r.report),
  }));
}

/** Unread warn and action reports, newest first, under their pixie's chat repo. */
function inboxReports(state: State): { repo: string; report: PixieReport }[] {
  return Object.values(state.reports)
    .filter((r) => r.read_at === null && r.severity !== "info")
    .sort((a, b) => b.created_at.localeCompare(a.created_at))
    .map((report) => ({ repo: `${PIXIE_REPO}${report.pixie_id}`, report }));
}

/** Unread action reports, of one pixie or of all. */
export function unreadActions(state: State, pixieId?: string): number {
  return Object.values(state.reports).filter(
    (r) =>
      r.read_at === null &&
      r.severity === "action" &&
      (pixieId === undefined || r.pixie_id === pixieId),
  ).length;
}

export function needsCount(state: State, repo?: string): number {
  const mine = (x: { repo: string }) => repo === undefined || x.repo === repo;
  return (
    Object.values(state.approvals).filter(mine).length +
    failures(state).filter(mine).length +
    stuckChats(state).filter(mine).length +
    inboxReports(state).filter(mine).length
  );
}

export function isRunning(state: State, repo: string): boolean {
  return projectChats(state).some(
    (s) => s.repo === repo && (s.state === "running" || s.state === "starting"),
  );
}

/** The event each tool call was made in, by tool use id. */
function callEvents(events: NestEvent[]): Map<string, number> {
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
  events: NestEvent[] | undefined,
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
