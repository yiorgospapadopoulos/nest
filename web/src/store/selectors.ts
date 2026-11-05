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
  ProviderFeature,
  ProviderInfo,
  Session,
  StuckFlag,
  TrackedAgent,
  TrackedTask,
  LocalModel,
} from "../api/types.ts";
import { isLocalModel, list, localModelValue, obj, str } from "../api/payloads.ts";
import { isWeak, LOCAL_DETAIL, LOCAL_TITLE, localDetail, localOptions } from "./local.ts";
import {
  CLAUDE,
  type ModelCatalog,
  modelLabel,
  newChatChoices,
  type NewChatChoices,
  realModels,
} from "./catalog.ts";
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

const NAMELESS = "\u00a0";

/**
 * The name to show on a chat's row and header: blank, keeping its line's height, until the
 * engine's name arrives. Needs you cards keep `title`, so what they ask about stays readable.
 */
export function shownTitle(session: Session): string {
  const ended =
    session.state === "failed" || session.state === "interrupted" || session.state === "closed";
  return session.title_pending === true && !ended ? NAMELESS : session.title;
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

// The groups of the shared UI rules (design/ui-rules.json). The lists show none since
// B102, as the Mac since B77; both clients keep the groups' order and names for the rules.
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

/** The engine an outside chat ran on, by name (B113). */
export const outsideEngineName = (chat: Pick<ClaudeChat, "engine">): string =>
  chat.engine === "codex" ? "Codex" : "Claude Code";

/** When the chat was last active, for its row's time and the list's order (B102). */
export function lastActivity(entry: ChatEntry): string {
  return entry.session === undefined ? entry.chat.last_activity_at : entry.session.updated_at;
}

const entryId = (entry: ChatEntry) =>
  entry.session === undefined ? entry.chat.id : entry.session.id;

function archived(entry: ChatEntry): boolean {
  return entry.session === undefined ? entry.chat.archived : entry.session.archived_at !== null;
}

/** A project's chats as the Mac's sidebar lists them (B77, B102). */
export interface ChatList {
  // Shown under a Pinned label only when there are any.
  pinned: ChatEntry[];
  // Every other chat whatever its state, under Chats.
  chats: ChatEntry[];
  // Folded at the bottom.
  archived: ChatEntry[];
}

/**
 * A project's chats in one list, latest activity first whatever their state (the later id
 * first at the same moment), pinned ones above and archived ones apart. Claude Code chats
 * are never pinned.
 */
export function chatList(state: State, repo: string): ChatList {
  const sessions: ChatEntry[] = projectChats(state)
    .filter((s) => s.repo === repo)
    .map((session) => ({ session, status: chatStatus(session, pendingFor(state, session.id)) }));
  const chats: ChatEntry[] = Object.values(state.claudeChats)
    .filter((c) => c.repo === repo)
    .map((chat) => ({ chat, status: CLAUDE_CHAT_STATUS }));
  const entries = [...sessions, ...chats].sort(
    (a, b) =>
      lastActivity(b).localeCompare(lastActivity(a)) || entryId(b).localeCompare(entryId(a)),
  );
  const live = entries.filter((e) => !archived(e));
  return {
    pinned: live.filter((e) => e.session?.pinned === true),
    chats: live.filter((e) => e.session?.pinned !== true),
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

/**
 * The pending approvals that need the user now. A review or merge waits while its chat is
 * at work: it cannot be acted on yet, and the turn may replace it.
 */
function waitingApprovals(state: State): Approval[] {
  return Object.values(state.approvals).filter((a) => {
    if (!isFinishedWork(a)) return true;
    const chat = state.sessions[a.session_id];
    return chat === undefined || !isAtWork(chat);
  });
}

const isFinishedWork = (a: Approval) => a.kind === "review" || a.kind === "merge";

/** Every pending item, failed check and stuck chat, by project in the order they are listed. */
export function inboxGroups(state: State): InboxGroup[] {
  const order = state.repos.map((r) => r.name);
  const rank = (repo: string) => (order.includes(repo) ? order.indexOf(repo) : order.length);
  const items = waitingApprovals(state).sort((a, b) => a.created_at.localeCompare(b.created_at));
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

/** Unread warn and action reports, newest first, as Needs you and the Pixies view list them. */
export function unreadReports(state: State): PixieReport[] {
  return Object.values(state.reports)
    .filter((r) => r.read_at === null && r.severity !== "info")
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/** Unread warn and action reports, newest first, under their pixie's chat repo. */
function inboxReports(state: State): { repo: string; report: PixieReport }[] {
  return unreadReports(state).map((report) => ({
    repo: `${PIXIE_REPO}${report.pixie_id}`,
    report,
  }));
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

/** The agent is working on this chat, so its finished work cannot be acted on yet. */
export function isAtWork(session: Session): boolean {
  return session.state === "starting" || session.state === "running" || session.state === "waiting";
}

/** The colour of what waits: review when it is only finished work, wait for anything else. */
export function needsTone(state: State, repo: string): "rev" | "wait" | null {
  if (needsCount(state, repo) === 0) return null;
  const mine = waitingApprovals(state).filter((a) => a.repo === repo);
  const others = needsCount(state, repo) - mine.length;
  return others === 0 && mine.every(isFinishedWork) ? "rev" : "wait";
}

export function needsCount(state: State, repo?: string): number {
  const mine = (x: { repo: string }) => repo === undefined || x.repo === repo;
  return (
    waitingApprovals(state).filter(mine).length +
    failures(state).filter(mine).length +
    stuckChats(state).filter(mine).length +
    inboxReports(state).filter(mine).length
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

// Engines (B91, B94), as NestKit's ProvidersStore: gating reads the daemon's lists, never an
// engine's name, so an engine not listed offers everything and the daemon still refuses.

/** The engines chats run on, the default first; Claude alone before the list loads. */
export function engineList(state: State): ProviderInfo[] {
  return (
    state.providers ?? [
      {
        name: CLAUDE,
        display_name: "Claude",
        signed_in: null,
        sign_in_hint: null,
        account: state.account,
        unsupported: [],
        version: null,
        tested: true,
        git_guard: true,
        state: "ready",
        state_detail: null,
        sign_in: "browser",
        login_command: null,
        installable: false,
      },
    ]
  );
}

/** A new chat can run on more than one engine, so the model menu offers the choice. */
export function offersEngineChoice(state: State): boolean {
  return state.providers !== null && engineList(state).length > 1;
}

/**
 * Whether a new chat can start on the engine now: installed, and not signed out. An engine
 * that signs in through the browser (Claude, Codex) stays offered signed out, as on the
 * Mac: the composer says to sign in, and its chats fail until then.
 */
export function engineReady(provider: ProviderInfo): boolean {
  if (provider.state !== "ready") return false;
  return provider.sign_in === "browser" || provider.signed_in !== false;
}

const ENGINE_STATE: Record<Exclude<ProviderInfo["state"], "ready">, string> = {
  not_installed: "Not installed",
  installing: "Installing...",
  install_failed: "Install failed",
};

/**
 * Whether a pixie can be set to run on the engine: installed, and one whose git commands
 * Nest can block, since a pixie's runs promise no commits (B107). Its sign-in can follow.
 */
export function pixieCanRunOn(state: State, provider: string): boolean {
  const listed = engineList(state).find((p) => p.name === provider);
  return listed === undefined || (listed.state === "ready" && listed.git_guard);
}

/** Why a new chat cannot start on the engine, in words; empty when it can. */
export function engineStateText(provider: ProviderInfo): string {
  if (provider.state !== "ready") return ENGINE_STATE[provider.state];
  return provider.signed_in === false ? "Not signed in" : "";
}

/** The engine's name; none is Claude, an engine not listed is named after itself. */
export function engineName(state: State, name: string | null | undefined): string {
  const engine = name ?? CLAUDE;
  const listed = engineList(state).find((p) => p.name === engine);
  return listed?.display_name ?? engine.charAt(0).toUpperCase() + engine.slice(1);
}

/** The grey line under an engine in a menu: why it cannot run (B107), else its plan. */
export function engineDetail(provider: ProviderInfo): string {
  const why = engineStateText(provider);
  return why !== "" ? why : (provider.account?.plan ?? "");
}

/**
 * The engine's real models and its default model; none is Claude, whose list from
 * before B102's loads stands in until its own list with a default arrives.
 */
export function catalogFor(state: State, provider: string | null | undefined): ModelCatalog {
  const engine = provider ?? CLAUDE;
  const list = state.modelLists[engine];
  // Any engine knows the local models, so their names and thinking read right (B116).
  const options = localOptions(state.local.list);
  const local = options.length === 0 ? {} : { local: options };
  if (list !== undefined) {
    return { models: realModels(list.models), defaultModel: list.default_model, ...local };
  }
  const old = engine === CLAUDE ? (state.models ?? []) : [];
  return { models: realModels(old), defaultModel: null, ...local };
}

/** One engine's part of the model menu. */
export interface ModelSection {
  provider: string;
  // The engine's name, or "Model" when there is no choice of engines.
  title: string;
  // Its plan, or why it cannot run, such as "Not signed in"; empty for none.
  detail: string;
  catalog: ModelCatalog;
  // False when a new chat cannot start on it (B107): its models show, not choosable.
  available: boolean;
  // The local models' section (B116), whose `provider` is the engine they run on.
  local?: boolean;
  // An engine's own models on the user's servers, listed apart from its hosted ones.
  engineLocal?: boolean;
  // Models shown but not choosable, such as a stopped server's local models.
  unavailable?: string[];
  // Local models weak at tools, whose line reads as a warning.
  weak?: string[];
}

/**
 * The local models under "Local", chosen on `engine` (D129: a new chat's is the "Local chats
 * run on" engine, an open chat's its own); none without any.
 */
function localSection(state: State, engine: string): ModelSection[] {
  const models = state.local.list?.models ?? [];
  if (models.length === 0) return [];
  const values = (pick: LocalModel[]) => pick.map((m) => localModelValue(m.id));
  return [
    {
      provider: engine,
      title: LOCAL_TITLE,
      detail: LOCAL_DETAIL,
      catalog: { models: localOptions(state.local.list), defaultModel: null },
      available: true,
      local: true,
      unavailable: values(models.filter((m) => !m.running)),
      weak: values(models.filter((m) => m.running && isWeak(m))),
    },
  ];
}

/**
 * The model menu's sections: a new chat's (`isDraft`) every engine Nest supports, so
 * choosing a model chooses the engine, one not installed or signed out shown but not
 * choosable; a chat that exists only its own engine's (`provider`, none is Claude). With
 * one engine, one Model section.
 */
export function modelSections(
  state: State,
  provider: string | null,
  isDraft: boolean,
): ModelSection[] {
  const own = provider ?? CLAUDE;
  const local = localSection(state, isDraft ? (state.local.list?.engine ?? CLAUDE) : own);
  const engines = engineSections(state, own, isDraft);
  return [...engines.map(hostedPart), ...engines.flatMap(localPart), ...local];
}

/** A section's unique key: an engine's name can head its local models' section too. */
export function sectionKey(section: ModelSection): string {
  if (section.local === true) return "local";
  return section.engineLocal === true ? `local:${section.provider}` : section.provider;
}

function hostedPart(section: ModelSection): ModelSection {
  const models = section.catalog.models.filter((m) => m.local !== true);
  return { ...section, catalog: { ...section.catalog, models } };
}

function localPart(section: ModelSection): ModelSection[] {
  const models = section.catalog.models.filter((m) => m.local === true);
  if (models.length === 0) return [];
  return [
    {
      ...section,
      title: LOCAL_TITLE,
      detail: localDetail(section.title),
      catalog: { ...section.catalog, models },
      engineLocal: true,
    },
  ];
}

function engineSections(state: State, own: string, isDraft: boolean): ModelSection[] {
  if (!offersEngineChoice(state)) {
    return [
      {
        provider: CLAUDE,
        title: "Model",
        detail: "",
        catalog: catalogFor(state, CLAUDE),
        available: true,
      },
    ];
  }
  if (!isDraft) {
    const listed = engineList(state).find((p) => p.name === own);
    return [
      {
        provider: own,
        title: listed?.display_name ?? engineName(state, own),
        detail: listed === undefined ? "" : engineDetail(listed),
        catalog: catalogFor(state, own),
        available: true,
      },
    ];
  }
  return engineList(state).map((p) => ({
    provider: p.name,
    title: p.display_name,
    detail: engineDetail(p),
    catalog: catalogFor(state, p.name),
    available: engineReady(p),
  }));
}

/** A model's name, after its engine's off Claude, such as "Codex · GPT-5.5". */
export function modelTitle(
  state: State,
  model: string | null,
  provider: string | null | undefined,
): string {
  const name = modelLabel(catalogFor(state, provider), model);
  // A local model goes by its own name on any engine (B116).
  if (isLocalModel(model)) return name;
  const engine = provider ?? CLAUDE;
  return engine === CLAUDE ? name : `${engineName(state, engine)} · ${name}`;
}

/** The model a chat runs: its own, or its engine's default for a chat without one. */
export function chatModel(state: State, session: Session): string | null {
  return session.model ?? catalogFor(state, session.provider).defaultModel;
}

/** Whether chats on the engine (none is Claude) can do it. */
export function supportsFeature(
  state: State,
  feature: ProviderFeature,
  provider: string | null | undefined,
): boolean {
  const engine = provider ?? CLAUDE;
  return state.providers?.find((p) => p.name === engine)?.unsupported.includes(feature) !== true;
}

/** What to tell the user before sending on an engine that said it is not signed in. */
export function signInHint(state: State, provider: string | null | undefined): string | null {
  const engine = provider ?? CLAUDE;
  const listed = state.providers?.find((p) => p.name === engine);
  if (listed?.signed_in !== false) return null;
  return listed.sign_in_hint ?? `${listed.display_name} isn't signed in.`;
}

/** A new chat's draft from the concrete agent defaults; null until they loaded. */
export function newChatDefaults(state: State): NewChatChoices | null {
  const defaults = state.agentDefaults;
  if (defaults === null) return null;
  return newChatChoices(defaults, catalogFor(state, defaults.provider));
}

/** One engine's line in the usage bar. */
export interface UsageBarLine {
  provider: string;
  name: string;
}

/**
 * Whether the engine has plan limits to show: Claude does, another engine unless the Mac
 * said it has no windows (B107: the ACP engines report tokens only).
 */
export function reportsLimits(state: State, provider: string): boolean {
  if (provider === CLAUDE) return true;
  const windows = state.engineLimits[provider]?.windows;
  return windows === undefined || windows.length > 0;
}

/** The other engines whose limits can show: signed in, and with windows to show. */
export function meteredOthers(state: State): ProviderInfo[] {
  return (state.providers ?? []).filter(
    (p) => p.name !== CLAUDE && p.signed_in === true && reportsLimits(state, p.name),
  );
}

/** Claude, then the other engines that said they are signed in, in the list's order. */
function meteredEngines(state: State): UsageBarLine[] {
  const others = meteredOthers(state);
  return [
    { provider: CLAUDE, name: engineName(state, CLAUDE) },
    ...others.map((p) => ({ provider: p.name, name: p.display_name })),
  ];
}

/**
 * The usage bar's lines (B102 item 23, 29): Claude and each other engine signed in, less
 * those unchecked on this device; Claude's alone when none is left, so the bar stays.
 */
export function usageBarLines(state: State): UsageBarLine[] {
  const engines = meteredEngines(state);
  const chosen = engines.filter((e) => !state.usageBarHidden.includes(e.provider));
  return chosen.length === 0 ? engines.slice(0, 1) : chosen;
}

/** A checkmark of Settings > Usage > "Top bar shows". */
export interface UsageBarChoice {
  provider: string;
  name: string;
  // "Not signed in" for an engine that said so: it shows only once signed in.
  detail: string;
  shown: boolean;
}

/** Every engine listed with limits, in its order, checked unless unchecked on this device. */
export function usageBarChoices(state: State): UsageBarChoice[] {
  const listed = engineList(state).filter((p) => reportsLimits(state, p.name));
  return listed.map((p) => ({
    provider: p.name,
    name: p.display_name,
    detail: p.signed_in === false ? engineDetail(p) : "",
    shown: !state.usageBarHidden.includes(p.name),
  }));
}
