import { contextOf, list, obj, prOf, queuedOf, str, stuckOf } from "../api/payloads.ts";
import type {
  Approval,
  Artifact,
  BackgroundSummary,
  Connector,
  Goal,
  GroupEntry,
  Habit,
  HabitRun,
  NestEvent,
  JsonObject,
  JsonValue,
  LimitWindow,
  Pixie,
  PixieReport,
  PixieTeam,
  RepoConfig,
  Session,
  TrackedAgent,
  TrackedTask,
  UsageLimits,
  UsagePeriod,
  PeriodUnit,
  ClaudeAccount,
  ClaudeCodeInfo,
} from "../api/types.ts";
import {
  withArtifact,
  withChatsDeleted,
  withList,
  withoutArtifact,
  withSeen,
} from "./artifacts.ts";
import {
  draftKey,
  NO_BACKGROUND,
  type BashRun,
  NO_DRAFT,
  type Action,
  type Draft,
  type InstallProgress,
  type SettingsState,
  type State,
  type Tracking,
} from "./state.ts";

function knownDrafts(
  drafts: Record<string, Draft>,
  { repos, sessions }: { repos: RepoConfig[]; sessions: Session[] },
): Record<string, Draft> {
  const known = new Set([
    ...sessions.map((s) => draftKey({ session: s.id })),
    ...repos.map((r) => draftKey({ repo: r.name })),
  ]);
  // Pixies load after this snapshot, so their drafts are kept (D072).
  const pixie = draftKey({ pixie: "" });
  return Object.fromEntries(
    Object.entries(drafts).filter(([key]) => known.has(key) || key.startsWith(pixie)),
  );
}

export function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "auth":
      // Signed out, refused or reloading: no live connection to restore.
      return { ...state, auth: action.auth, reconnecting: false };
    case "reconnecting":
      return { ...state, reconnecting: action.on };
    case "loaded":
      return {
        ...state,
        auth: "ready",
        repos: action.repos,
        // The session list leaves pixie chats out (D072); the ones known stay.
        sessions: Object.fromEntries([
          ...Object.values(state.sessions)
            .filter((s) => s.pixie_id != null)
            .map((s) => [s.id, s] as const),
          ...action.sessions.map((s) => [s.id, s] as const),
        ]),
        approvals: Object.fromEntries(
          action.approvals.filter((a) => a.status === "pending").map((a) => [a.id, a]),
        ),
        // The first snapshot drops saved drafts of chats and projects removed while the app
        // was closed; after that, the live events remove them.
        drafts: state.auth === "ready" ? state.drafts : knownDrafts(state.drafts, action),
      };
    case "repo":
      return upsertRepo(state, action.repo);
    case "repoRemoved":
      return { ...state, repos: state.repos.filter((r) => r.name !== action.name) };
    case "session":
      return upsertSession(state, action.session);
    case "sessionRemoved":
      return removeSession(state, action.id);
    case "pixies": {
      // Drafts of pixies deleted while the app was closed go with them.
      const known = new Set(action.pixies.map((p) => draftKey({ pixie: p.id })));
      const pixie = draftKey({ pixie: "" });
      return {
        ...state,
        pixies: Object.fromEntries(action.pixies.map((p) => [p.id, p])),
        drafts: Object.fromEntries(
          Object.entries(state.drafts).filter(([key]) => !key.startsWith(pixie) || known.has(key)),
        ),
      };
    }
    case "pixie":
      return { ...state, pixies: { ...state.pixies, [action.pixie.id]: action.pixie } };
    case "pixieRemoved":
      return withoutPixie(state, action.id);
    case "teams":
      return { ...state, teams: Object.fromEntries(action.teams.map((t) => [t.id, t])) };
    case "team":
      return { ...state, teams: { ...state.teams, [action.team.id]: action.team } };
    case "teamRemoved":
      return withoutTeam(state, action.id);
    case "teamFolded": {
      const others = state.foldedTeams.filter((id) => id !== action.id);
      const folded = action.folded ? [...others, action.id] : others;
      return folded.length === state.foldedTeams.length ? state : { ...state, foldedTeams: folded };
    }
    case "reports":
      return { ...state, reports: Object.fromEntries(action.reports.map((r) => [r.id, r])) };
    case "report":
      return { ...state, reports: { ...state.reports, [action.report.id]: action.report } };
    case "reportsRead":
      return reportsRead(state, action.ids, action.at);
    case "habits":
      return { ...state, habits: { ...state.habits, [action.pixieId]: action.habits } };
    case "habit":
      return upsertHabit(state, action.habit);
    case "habitRemoved":
      return removeHabit(state, action.pixieId, action.id);
    case "habitRuns":
      return { ...state, habitRuns: { ...state.habitRuns, [action.habitId]: action.runs } };
    case "habitRun":
      return upsertRun(state, action.run);
    case "claudeChats":
      return {
        ...state,
        claudeChats: Object.fromEntries(action.chats.map((chat) => [chat.id, chat])),
      };
    case "claudeChat":
      return { ...state, claudeChats: { ...state.claudeChats, [action.chat.id]: action.chat } };
    case "claudeChatRemoved":
      return {
        ...state,
        claudeChats: Object.fromEntries(
          Object.entries(state.claudeChats).filter(([id]) => id !== action.id),
        ),
      };
    case "showAutomated":
      return { ...state, showAutomated: action.on };
    case "approval":
      return upsertApproval(state, action.approval);
    case "tracking":
      return { ...state, tracking: { ...state.tracking, [action.id]: action.tracking } };
    case "goals":
      return withGoals(state, action.repo, action.goals);
    case "pixieGroups":
      return { ...state, pixieGroups: action.groups };
    case "pixieGroup":
      return withGroup(state, action.id, action.group);
    case "transcriptOpened":
      return {
        ...state,
        transcripts: { ...state.transcripts, [action.id]: state.transcripts[action.id] ?? [] },
        history: { ...state.history, [action.id]: state.history[action.id] ?? "loading" },
      };
    case "transcriptLoaded":
      return {
        ...state,
        transcripts: {
          ...state.transcripts,
          [action.id]: merge(state.transcripts[action.id] ?? [], action.events),
        },
        history: { ...state.history, [action.id]: "loaded" },
      };
    case "historyFailed":
      // A later refresh that fails keeps the history already shown.
      return state.history[action.id] === "loading"
        ? { ...state, history: { ...state.history, [action.id]: "failed" } }
        : state;
    case "transcriptClosed":
      return {
        ...state,
        transcripts: omit(state.transcripts, action.id),
        history: omit(state.history, action.id),
      };
    case "queued":
      return { ...state, queued: { ...state.queued, [action.id]: action.queued } };
    case "queuedRemoved":
      return {
        ...state,
        queued: {
          ...state.queued,
          [action.id]: (state.queued[action.id] ?? []).filter((q) => q.id !== action.queuedId),
        },
      };
    case "event":
      return applyEvent(state, action.event);
    case "replayed": {
      // Streamed text and thinking already followed these events when they arrived.
      const next = action.events.reduce(applyEvent, state);
      const { live, thinking, thoughts, agentLive } = state;
      return { ...next, live, thinking, thoughts, agentLive };
    }
    case "liveCleared":
      return clearAgents(clearThinking(clearLive(state, action.id), action.id), action.id);
    case "draftText":
      return patchDraft(state, action.key, () => ({ text: action.text }));
    case "draftFileAdded":
      return patchDraft(state, action.key, (d) => ({ files: [...d.files, action.file] }));
    case "draftFileRemoved":
      return patchDraft(state, action.key, (d) => ({
        files: d.files.filter((f) => f.id !== action.fileId),
      }));
    case "draftFilled":
      return patchDraft(state, action.key, () => ({ text: action.text, files: action.files }));
    case "draftSent":
      return draftSent(state, action.key, action.text, action.fileIds, action.to ?? action.key);
    case "bashStarted": {
      const run = { id: action.runId, command: action.command, result: null, error: null };
      return { ...state, bash: { ...state.bash, [action.id]: [...bashOf(state, action.id), run] } };
    }
    case "bashFinished": {
      const { result = null, error = null } = action;
      // A chat deleted meanwhile has none.
      if (!bashOf(state, action.id).some((run) => run.id === action.runId)) return state;
      const runs = bashOf(state, action.id).map((run) =>
        run.id === action.runId ? { ...run, result, error } : run,
      );
      return { ...state, bash: { ...state.bash, [action.id]: runs } };
    }
    case "bashSent": {
      const runs = bashOf(state, action.id).filter((run) => !action.runIds.includes(run.id));
      return { ...state, bash: { ...state.bash, [action.id]: runs } };
    }
    case "connectors":
      return { ...state, connectors: action.connectors };
    case "limits":
      return { ...state, limits: action.limits };
    case "usageView": {
      const { period } = state.usage;
      const kept = period !== null && shows(period, action.unit, action.date) ? period : null;
      return { ...state, usage: { unit: action.unit, date: action.date, period: kept } };
    }
    case "usagePeriod": {
      const { unit, date } = state.usage;
      // A period that arrives after moving on is dropped.
      if (!shows(action.period, unit, date)) return state;
      return { ...state, usage: { ...state.usage, period: action.period } };
    }
    case "notifications":
      return { ...state, notifications: action.notifications };
    case "models":
      return { ...state, models: action.models };
    case "account":
      return { ...state, account: action.account };
    case "agentDefaults":
      return { ...state, agentDefaults: action.defaults };
    case "settings":
      return { ...state, settings: { ...state.settings, ...action.change } };
    case "artifacts":
      return withList(state, action.filter, action.artifacts);
    case "artifact":
      return withArtifact(state, action.artifact);
    case "artifactRemoved":
      return withoutArtifact(state, action.id);
    case "unseenArtifacts":
      return { ...state, unseenArtifacts: action.unseen };
    case "toast":
      return { ...state, toast: action.toast };
  }
}

function withSettings(state: State, change: Partial<SettingsState>): State {
  return { ...state, settings: { ...state.settings, ...change } };
}

/** Fold one live event from the socket into the state. */
export function applyEvent(state: State, event: NestEvent): State {
  const next = withTranscript(state, event);
  const id = event.session_id;
  const p = event.payload;
  switch (event.type) {
    case "repo.updated": {
      const changed = p.repo as unknown as RepoConfig;
      return {
        ...next,
        repos: next.repos.map((r) => (r.name === changed.name ? changed : r)),
      };
    }
    case "repo.added":
      return upsertRepo(next, p.repo as unknown as RepoConfig);
    case "repo.removed":
      return { ...next, repos: next.repos.filter((r) => r.name !== str(p.name)) };
    case "repos.reordered":
      return { ...next, repos: inOrder(next.repos, list(p.order).map(String)) };
    case "session.created":
    case "session.updated":
      return upsertSession(next, p.session as unknown as Session);
    case "session.state": {
      const cleared = clearThinking(next, id);
      return patchSession(p.state === "running" ? cleared : clearAgents(cleared, id), id, {
        state: p.state as Session["state"],
        last_error: str(p.error),
      });
    }
    case "session.workspace":
      return patchSession(next, id, { branch: str(p.branch), worktree_path: str(p.path) });
    case "pr.opened":
      return patchSession(next, id, { pr_url: str(p.url) });
    case "session.pr":
      return patchSession(next, id, { pr: prOf(p.pr) });
    case "session.context":
      return patchSession(next, id, { context: contextOf(p.context) });
    case "session.stuck":
      return patchSession(next, id, { stuck: stuckOf(p) });
    case "session.unstuck":
      return patchSession(next, id, { stuck: null });
    case "session.queued":
      // The full list after every change; the last one wins.
      return id === null ? next : { ...next, queued: { ...next.queued, [id]: queuedOf(p.queued) } };
    case "session.deleted": {
      const deleted = str(p.session_id) ?? "";
      return withChatsDeleted(removeSession(next, deleted), "session_id", deleted);
    }
    case "session.rewound":
      return rewound(next, id, p);
    case "approval.created":
    case "approval.resolved":
      return upsertApproval(next, p.approval as unknown as Approval);
    case "session.pixies":
      return id === null ? next : withGroup(next, id, list(p.group) as unknown as GroupEntry[]);
    case "session.tasks":
      return patchTracking(next, id, { tasks: list(p.tasks) as unknown as TrackedTask[] });
    case "session.agents":
      return patchTracking(next, id, {
        agents: list(p.agents) as unknown as TrackedAgent[],
        // Daemons before B22 send agents only.
        ...(p.background === undefined
          ? {}
          : { background: p.background as unknown as BackgroundSummary }),
      });
    case "session.delta":
      return id === null
        ? next
        : { ...next, live: { ...next.live, [id]: (next.live[id] ?? "") + (str(p.text) ?? "") } };
    case "session.thinking":
      return id === null || p.active !== true
        ? clearThinking(next, id)
        : { ...clearThinking(next, id), thinking: { ...next.thinking, [id]: event.ts } };
    case "session.thinking_delta":
      // A subagent's thinking shows once its message arrives.
      return id === null || p.parent_tool_use_id != null
        ? next
        : { ...next, thoughts: { ...next.thoughts, [id]: (next.thoughts[id] ?? "") + text(p) } };
    case "session.subagent_delta": {
      const parent = str(p.parent_tool_use_id);
      if (id === null || parent === null) return next;
      const streams = next.agentLive[id] ?? {};
      const streamed = { ...streams, [parent]: (streams[parent] ?? "") + text(p) };
      return { ...next, agentLive: { ...next.agentLive, [id]: streamed } };
    }
    case "session.message": {
      // A subagent's message replaces only its own streamed text.
      const parent = str(p.parent_tool_use_id);
      return parent === null
        ? clearThinking(clearLive(next, id), id)
        : clearAgent(next, id, parent);
    }
    case "session.result":
      return clearThinking(clearLive(next, id), id);
    case "pixie.updated": {
      const pixie = p.pixie as unknown as Pixie;
      return { ...next, pixies: { ...next.pixies, [pixie.id]: pixie } };
    }
    case "pixie.deleted": {
      // Its chats went with it.
      const deleted = str(p.pixie_id) ?? "";
      return withChatsDeleted(withoutPixie(next, deleted), "pixie_id", deleted);
    }
    case "pixie_team.updated": {
      const team = p.team as unknown as PixieTeam;
      return { ...next, teams: { ...next.teams, [team.id]: team } };
    }
    case "pixie_team.deleted":
      return withoutTeam(next, str(p.id) ?? "");
    case "pixie.report":
      return reduce(next, { type: "report", report: p.report as unknown as PixieReport });
    case "pixie.report_read":
      return reportsRead(next, list(p.ids).map(String), event.ts);
    case "habit.updated":
      return upsertHabit(next, p.habit as unknown as Habit);
    case "habit.deleted":
      return removeHabit(next, str(p.pixie_id) ?? "", str(p.id) ?? "");
    case "habit.run_updated":
      return upsertRun(next, p.run as unknown as HabitRun);
    case "connectors.updated":
      return { ...next, connectors: list(p.connectors) as unknown as Connector[] };
    case "usage.updated":
      return { ...next, limits: limitsOf(p, event.ts, next.limits) };
    case "account.claude":
      return withSettings(next, { claude: p as unknown as ClaudeAccount });
    case "claude_code.updated":
      return withSettings(next, { claudeCode: p as unknown as ClaudeCodeInfo });
    case "claude_code.install":
      return withSettings(next, { install: p as unknown as InstallProgress });
    case "artifact.saved":
      return withUnseen(withArtifact(next, p.artifact as unknown as Artifact, true), p);
    case "artifact.seen":
      return withUnseen(withSeen(next, str(p.artifact_id) ?? ""), p);
    case "artifact.deleted":
      return withUnseen(withoutArtifact(next, str(p.artifact_id) ?? ""), p);
    default:
      return next;
  }
}

/** The badge's count from an artifact event, which carries the new total. */
function withUnseen(state: State, p: JsonObject): State {
  return typeof p.unseen === "number" ? { ...state, unseenArtifacts: p.unseen } : state;
}

/**
 * The goals list every chat of the project's list with steps showing, so a known list of
 * one it leaves out (cleared by an event this device missed) shows none now.
 */
function withGoals(state: State, repo: string, goals: Goal[]): State {
  const listed = new Set(goals.map((g) => g.session_id));
  const cleared = Object.values(state.sessions)
    .filter(
      (s) =>
        s.repo === repo &&
        s.archived_at === null &&
        s.pixie_id == null &&
        !listed.has(s.id) &&
        s.id in state.tracking,
    )
    .reduce((next, s) => patchTracking(next, s.id, { tasks: [] }), state);
  return goals.reduce((next, g) => patchTracking(next, g.session_id, { tasks: g.tasks }), cleared);
}

/** The chat's pixie group; an empty one leaves the record. */
function withGroup(state: State, id: string, group: GroupEntry[]): State {
  const others = omit(state.pixieGroups, id);
  return { ...state, pixieGroups: group.length === 0 ? others : { ...others, [id]: group } };
}

/** The state without the pixie, its saved draft, habits and reports. */
function withoutPixie(state: State, id: string): State {
  return {
    ...state,
    pixies: omit(state.pixies, id),
    drafts: omit(state.drafts, draftKey({ pixie: id })),
    habits: omit(state.habits, id),
    reports: Object.fromEntries(Object.entries(state.reports).filter(([, r]) => r.pixie_id !== id)),
  };
}

/** Reports not read yet among `ids` read at `at`; others keep when they were read. */
function reportsRead(state: State, ids: string[], at: string): State {
  const unread = ids.flatMap((id) => {
    const report = state.reports[id];
    return report?.read_at === null ? [report] : [];
  });
  if (unread.length === 0) return state;
  const reports = { ...state.reports };
  for (const report of unread) reports[report.id] = { ...report, read_at: at };
  return { ...state, reports };
}

/** A habit in its pixie's list, when that list was loaded: a partial list would mislead. */
function upsertHabit(state: State, habit: Habit): State {
  const habits = state.habits[habit.pixie_id];
  if (habits === undefined) return state;
  const known = habits.some((h) => h.id === habit.id);
  return {
    ...state,
    habits: {
      ...state.habits,
      [habit.pixie_id]: known
        ? habits.map((h) => (h.id === habit.id ? habit : h))
        : [...habits, habit],
    },
  };
}

function removeHabit(state: State, pixieId: string, id: string): State {
  const habits = state.habits[pixieId];
  if (habits === undefined) return state;
  return {
    ...state,
    habits: { ...state.habits, [pixieId]: habits.filter((h) => h.id !== id) },
    habitRuns: omit(state.habitRuns, id),
  };
}

/** A run in its habit's open history (a new one first) and as that habit's last run. */
function upsertRun(state: State, run: HabitRun): State {
  const runs = state.habitRuns[run.habit_id];
  const habits = state.habits[run.pixie_id];
  return {
    ...state,
    habitRuns:
      runs === undefined
        ? state.habitRuns
        : {
            ...state.habitRuns,
            [run.habit_id]: runs.some((r) => r.id === run.id)
              ? runs.map((r) => (r.id === run.id ? run : r))
              : [run, ...runs],
          },
    habits:
      habits === undefined
        ? state.habits
        : {
            ...state.habits,
            [run.pixie_id]: habits.map((h) =>
              h.id === run.habit_id ? { ...h, last_run: run } : h,
            ),
          },
  };
}

/** The state without the team; its pixies stay, without a team, as the Mac leaves them. */
function withoutTeam(state: State, id: string): State {
  return {
    ...state,
    teams: omit(state.teams, id),
    pixies: Object.fromEntries(
      Object.entries(state.pixies).map(([key, p]) => [
        key,
        p.team_id === id ? { ...p, team_id: null } : p,
      ]),
    ),
  };
}

function withTranscript(state: State, event: NestEvent): State {
  const id = event.session_id;
  if (id === null || event.id === null) return state;
  const events = state.transcripts[id];
  if (events === undefined || (events.at(-1)?.id ?? 0) >= event.id) return state;
  return { ...state, transcripts: { ...state.transcripts, [id]: [...events, event] } };
}

/**
 * A conversation rewind (B59) deleted the chat's events from the rewound message through
 * `through`; the transcript drops them too. What is built from them follows.
 */
function rewound(state: State, id: string | null, p: JsonObject): State {
  const events = id === null ? undefined : state.transcripts[id];
  const { message, through } = p;
  if (events === undefined || typeof message !== "number" || typeof through !== "number") {
    return state;
  }
  const kept = events.filter((e) => Number(e.id) < message || Number(e.id) > through);
  return { ...state, transcripts: { ...state.transcripts, [String(id)]: kept } };
}

function merge(current: NestEvent[], loaded: NestEvent[]): NestEvent[] {
  // Every transcript event is a stored one, so ids are never null here.
  const byId = new Map([...loaded, ...current].map((event) => [Number(event.id), event]));
  return [...byId.values()].sort((a, b) => Number(a.id) - Number(b.id));
}

function bashOf(state: State, id: string): BashRun[] {
  return state.bash[id] ?? [];
}

/** The projects sorted by the shared order (D090); ones it leaves out keep their order after. */
function inOrder(repos: RepoConfig[], order: string[]): RepoConfig[] {
  const rank = (name: string) => {
    const at = order.indexOf(name);
    return at === -1 ? order.length : at;
  };
  return [...repos].sort((a, b) => rank(a.name) - rank(b.name));
}

function upsertRepo(state: State, repo: RepoConfig): State {
  const known = state.repos.some((r) => r.name === repo.name);
  return {
    ...state,
    repos: known
      ? state.repos.map((r) => (r.name === repo.name ? repo : r))
      : [...state.repos, repo],
  };
}

function upsertSession(state: State, session: Session): State {
  return { ...state, sessions: { ...state.sessions, [session.id]: session } };
}

function patchSession(state: State, id: string | null, patch: Partial<Session>): State {
  const current = id === null ? undefined : state.sessions[id];
  return current === undefined ? state : upsertSession(state, { ...current, ...patch });
}

function removeSession(state: State, id: string): State {
  const without = <T>(record: Record<string, T>) =>
    Object.fromEntries(Object.entries(record).filter(([key]) => key !== id));
  return {
    ...state,
    sessions: without(state.sessions),
    approvals: Object.fromEntries(
      Object.entries(state.approvals).filter(([, a]) => a.session_id !== id),
    ),
    tracking: without(state.tracking),
    pixieGroups: without(state.pixieGroups),
    transcripts: without(state.transcripts),
    history: without(state.history),
    live: without(state.live),
    thinking: without(state.thinking),
    thoughts: without(state.thoughts),
    agentLive: without(state.agentLive),
    queued: without(state.queued),
    bash: without(state.bash),
    drafts: omit(state.drafts, draftKey({ session: id })),
  };
}

function upsertApproval(state: State, approval: Approval): State {
  const others = Object.entries(state.approvals).filter(([id]) => id !== approval.id);
  const approvals = Object.fromEntries(others);
  if (approval.status === "pending") approvals[approval.id] = approval;
  return { ...state, approvals };
}

function patchTracking(state: State, id: string | null, patch: Partial<Tracking>): State {
  if (id === null) return state;
  const current = state.tracking[id] ?? { tasks: [], agents: [], background: NO_BACKGROUND };
  return { ...state, tracking: { ...state.tracking, [id]: { ...current, ...patch } } };
}

function clearLive(state: State, id: string | null): State {
  if (id === null || !(id in state.live)) return state;
  return { ...state, live: omit(state.live, id) };
}

function clearThinking(state: State, id: string | null): State {
  if (id === null || !(id in state.thinking || id in state.thoughts)) return state;
  return { ...state, thinking: omit(state.thinking, id), thoughts: omit(state.thoughts, id) };
}

function clearAgents(state: State, id: string | null): State {
  if (id === null || !(id in state.agentLive)) return state;
  return { ...state, agentLive: omit(state.agentLive, id) };
}

function clearAgent(state: State, id: string | null, parent: string): State {
  const streams = id === null ? undefined : state.agentLive[id];
  if (id === null || streams === undefined || !(parent in streams)) return state;
  return { ...state, agentLive: { ...state.agentLive, [id]: omit(streams, parent) } };
}

/** A delta's text; the daemon never sends an empty one. */
function text(p: JsonObject): string {
  return str(p.text) ?? "";
}

function patchDraft(state: State, key: string, patch: (draft: Draft) => Partial<Draft>): State {
  const current = state.drafts[key] ?? NO_DRAFT;
  return { ...state, drafts: { ...state.drafts, [key]: { ...current, ...patch(current) } } };
}

/**
 * The draft without the text and files that were sent, under `to`; gone once nothing is
 * left. A new chat's draft moves to the chat its first message created.
 */
function draftSent(state: State, key: string, text: string, fileIds: string[], to: string): State {
  const current = state.drafts[key] ?? NO_DRAFT;
  // Text typed after the sent text stays; a sent part edited meanwhile keeps it all.
  const rest = current.text.startsWith(text)
    ? current.text.slice(text.length).trimStart()
    : current.text;
  const files = current.files.filter((f) => !fileIds.includes(f.id));
  const drafts = omit(state.drafts, key);
  if (rest === "" && files.length === 0) return { ...state, drafts };
  return { ...state, drafts: { ...drafts, [to]: { text: rest, files } } };
}

function omit<T>(record: Record<string, T>, id: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([key]) => key !== id));
}

/** The reported windows; one the event leaves out keeps its last report, as on the daemon. */
/** Whether `period` is the `unit` holding `date`, or the current one when `date` is null. */
function shows(period: UsagePeriod, unit: PeriodUnit, date: string | null): boolean {
  if (period.unit !== unit) return false;
  return date === null ? period.current : period.start <= date && date <= period.end;
}

function limitsOf(payload: JsonObject, ts: string, previous: UsageLimits | null): UsageLimits {
  const window = (value: JsonValue | undefined, last: LimitWindow | null): LimitWindow | null => {
    const w = obj(value);
    return typeof w.utilization === "number"
      ? { utilization: w.utilization, resets_at: str(w.resets_at), updated_at: ts }
      : last;
  };
  return {
    five_hour: window(payload.five_hour, previous?.five_hour ?? null),
    seven_day: window(payload.seven_day, previous?.seven_day ?? null),
  };
}
