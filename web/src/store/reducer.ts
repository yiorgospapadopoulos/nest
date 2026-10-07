import { contextOf, list, obj, prOf, queuedOf, str, stuckOf } from "../api/payloads.ts";
import type {
  Approval,
  BackgroundSummary,
  Connector,
  HarnessEvent,
  JsonObject,
  JsonValue,
  LimitWindow,
  RepoConfig,
  Session,
  TrackedAgent,
  TrackedTask,
  UsageLimits,
} from "../api/types.ts";
import {
  draftKey,
  NO_BACKGROUND,
  NO_DRAFT,
  type Action,
  type Draft,
  type State,
  type Tracking,
} from "./state.ts";

export function reduce(state: State, action: Action): State {
  switch (action.type) {
    case "auth":
      return { ...state, auth: action.auth };
    case "loaded":
      return {
        ...state,
        auth: "ready",
        repos: action.repos,
        sessions: Object.fromEntries(action.sessions.map((s) => [s.id, s])),
        approvals: Object.fromEntries(
          action.approvals.filter((a) => a.status === "pending").map((a) => [a.id, a]),
        ),
      };
    case "session":
      return upsertSession(state, action.session);
    case "sessionRemoved":
      return removeSession(state, action.id);
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
    case "transcriptOpened":
      return {
        ...state,
        transcripts: { ...state.transcripts, [action.id]: state.transcripts[action.id] ?? [] },
      };
    case "transcriptLoaded":
      return {
        ...state,
        transcripts: {
          ...state.transcripts,
          [action.id]: merge(state.transcripts[action.id] ?? [], action.events),
        },
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
    case "liveCleared":
      return clearThinking(clearLive(state, action.id), action.id);
    case "draftText":
      return patchDraft(state, action.key, () => ({ text: action.text }));
    case "draftFileAdded":
      return patchDraft(state, action.key, (d) => ({ files: [...d.files, action.file] }));
    case "draftFileRemoved":
      return patchDraft(state, action.key, (d) => ({
        files: d.files.filter((f) => f.id !== action.fileId),
      }));
    case "draftCleared":
      return { ...state, drafts: omit(state.drafts, action.key) };
    case "connectors":
      return { ...state, connectors: action.connectors };
    case "limits":
      return { ...state, limits: action.limits };
    case "notifications":
      return { ...state, notifications: action.notifications };
    case "models":
      return { ...state, models: action.models };
    case "account":
      return { ...state, account: action.account };
    case "agentDefaults":
      return { ...state, agentDefaults: action.defaults };
    case "toast":
      return { ...state, toast: action.toast };
  }
}

/** Fold one live event from the socket into the state. */
export function applyEvent(state: State, event: HarnessEvent): State {
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
    case "session.created":
    case "session.updated":
      return upsertSession(next, p.session as unknown as Session);
    case "session.state":
      return patchSession(clearThinking(next, id), id, {
        state: p.state as Session["state"],
        last_error: str(p.error),
      });
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
    case "session.deleted":
      return removeSession(next, str(p.session_id) ?? "");
    case "approval.created":
    case "approval.resolved":
      return upsertApproval(next, p.approval as unknown as Approval);
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
        : { ...next, thinking: { ...next.thinking, [id]: event.ts } };
    case "session.message":
    case "session.result":
      return clearThinking(clearLive(next, id), id);
    case "connectors.updated":
      return { ...next, connectors: list(p.connectors) as unknown as Connector[] };
    case "usage.updated":
      return { ...next, limits: limitsOf(p, event.ts, next.limits) };
    default:
      return next;
  }
}

function withTranscript(state: State, event: HarnessEvent): State {
  const id = event.session_id;
  if (id === null || event.id === null) return state;
  const events = state.transcripts[id];
  if (events === undefined || (events.at(-1)?.id ?? 0) >= event.id) return state;
  return { ...state, transcripts: { ...state.transcripts, [id]: [...events, event] } };
}

function merge(current: HarnessEvent[], loaded: HarnessEvent[]): HarnessEvent[] {
  // Every transcript event is a stored one, so ids are never null here.
  const byId = new Map([...loaded, ...current].map((event) => [Number(event.id), event]));
  return [...byId.values()].sort((a, b) => Number(a.id) - Number(b.id));
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
    transcripts: without(state.transcripts),
    live: without(state.live),
    thinking: without(state.thinking),
    queued: without(state.queued),
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
  if (id === null || !(id in state.thinking)) return state;
  return { ...state, thinking: omit(state.thinking, id) };
}

function patchDraft(state: State, key: string, patch: (draft: Draft) => Partial<Draft>): State {
  const current = state.drafts[key] ?? NO_DRAFT;
  return { ...state, drafts: { ...state.drafts, [key]: { ...current, ...patch(current) } } };
}

function omit<T>(record: Record<string, T>, id: string): Record<string, T> {
  return Object.fromEntries(Object.entries(record).filter(([key]) => key !== id));
}

/** The reported windows; one the event leaves out keeps its last report, as on the daemon. */
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
