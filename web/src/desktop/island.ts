// What the pixie pill shows (B114 on the Mac, D140; pill A of B117), ported from NestKit's
// IslandState.swift: the working pixies on the left, the ones that finished or need the user
// on the right until their chat is seen, and Nightshade when no pixie works.
import type {
  Approval,
  GroupEntry,
  HabitRun,
  Pixie,
  PixieTeam,
  TeamMember,
  TrackedAgent,
} from "../api/types.ts";
import { approvalLine, lineText } from "../screens/inbox/needsLine.ts";

export type IslandOrder = "newest" | "oldest";

export type IslandStatus = "working" | "needsYou" | "seen" | "done" | "failed" | "interrupted";

export const STATUS_WORDS: Record<IslandStatus, string> = {
  working: "Working",
  needsYou: "Needs you",
  seen: "Needs you",
  done: "Done",
  failed: "Failed",
  interrupted: "Interrupted",
};

/** Wants the user's eye: orange on the pill and in the +N. */
export function isAlert(status: IslandStatus): boolean {
  return status === "needsYou" || status === "failed" || status === "interrupted";
}

export type IslandFigure = { pixie: Pixie } | { team: PixieTeam; members: TeamMember[] };

/** The chat a click opens: the chat the work happens in. */
export type IslandPlace =
  | { chat: string; repo: string | null }
  | { pixieChat: string; pixie: string }
  | { habitRun: string };

export function placeSession(place: IslandPlace): string {
  if ("chat" in place) return place.chat;
  return "pixieChat" in place ? place.pixieChat : place.habitRun;
}

export interface IslandEntry {
  // "<session>/pixie:<id>" or "<session>/team:<id>", or "habit:<session>".
  id: string;
  figure: IslandFigure;
  label: string;
  place: IslandPlace;
  approvalId: string | null;
  status: IslandStatus;
  // When the current state began (ms): a call's start, its finish, the approval's creation.
  since: number;
  activity: string;
}

export type Nightshade = "idle" | "working" | "asleep";

/** A chat apart from its pixies: whether it works, for Nightshade. */
export interface IslandChat {
  repo: string | null;
  working: boolean;
  updatedAt: number;
  // A project chat, or a pixie's own chat; not a habit run's.
  normal: boolean;
}

export interface IslandSnapshot {
  groups: Record<string, GroupEntry[]>;
  agents: Record<string, TrackedAgent[]>;
  // Pending approvals.
  approvals: Approval[];
  // The latest run of each habit.
  habitRuns: HabitRun[];
  pixies: Pixie[];
  teams: PixieTeam[];
  chats: Record<string, IslandChat>;
  // When each chat was last seen (ms), by session id.
  seen: Record<string, number>;
  // When the pill first showed on this device: older finishes never show.
  installedAt: number;
  order: IslandOrder;
  // Show the island (Settings > Appearance); off shows nothing.
  shown: boolean;
  now: number;
  // When this pill started, so Nightshade starts awake.
  awakeSince: number | null;
}

export interface IslandState {
  left: IslandEntry[];
  right: IslandEntry[];
  list: IslandEntry[];
  // Nightshade on the left while no pixie works there.
  nightshade: Nightshade | null;
  // Bluebell resting on the right while nothing at all shows.
  restingBluebell: boolean;
}

// Nightshade falls asleep after this long with nothing running.
export const SLEEP_AFTER_MS = 120_000;

// What stops a call until the user answers.
const BLOCKING = new Set<Approval["kind"]>(["permission", "question", "plan"]);

const time = (iso: string | null | undefined) => (iso == null ? null : Date.parse(iso));

interface Standing {
  status: IslandStatus;
  since: number;
  approval: Approval | null;
  activity: string;
}

/** The approval's Needs you line, as the Mac's NeedsYouLine. */
function line(approval: Approval): string {
  return lineText(approvalLine(approval, null));
}

/**
 * Needs you while a blocking approval waits (seen once the chat was seen after it came),
 * else working while the call runs, else done, failed or interrupted when it finished after
 * the chat was last seen and after the pill first showed.
 */
function standing(
  snapshot: IslandSnapshot,
  session: string,
  approvals: Approval[],
  state: string,
  finished: number,
  started: number,
): Standing | null {
  const seen = snapshot.seen[session];
  const byAge = [...approvals].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const first = byAge[0];
  if (first !== undefined) {
    const asking = byAge.find((a) => seen === undefined || Date.parse(a.created_at) > seen);
    if (asking !== undefined) {
      return {
        status: "needsYou",
        since: Date.parse(asking.created_at),
        approval: asking,
        activity: line(asking),
      };
    }
    return {
      status: "seen",
      since: seen ?? Date.parse(first.created_at),
      approval: first,
      activity: line(first),
    };
  }
  if (state === "running")
    return { status: "working", since: started, approval: null, activity: "" };
  const ended: Record<string, IslandStatus> = {
    done: "done",
    failed: "failed",
    interrupted: "interrupted",
  };
  const status = ended[state];
  if (status === undefined) return null;
  if (finished <= snapshot.installedAt || (seen !== undefined && finished <= seen)) return null;
  return {
    status,
    since: finished,
    approval: null,
    activity: status === "done" ? "Finished" : STATUS_WORDS[status],
  };
}

function descends(agent: TrackedAgent, call: string, agents: TrackedAgent[]): boolean {
  let parent = agent.parent ?? null;
  for (let hops = 0; parent !== null && hops <= agents.length; hops++) {
    if (parent === call) return true;
    const id: string = parent;
    parent = agents.find((a) => a.id === id)?.parent ?? null;
  }
  return false;
}

/**
 * The call's live activity, else its description, else "Working"; a team's is its most
 * recently started running member's (an agent inside the leader's call).
 */
function workingActivity(snapshot: IslandSnapshot, session: string, call: string, team: boolean) {
  const agents = snapshot.agents[session] ?? [];
  const own = agents.find((a) => a.id === call);
  if (team) {
    const inside = agents
      .filter((a) => a.status === "running" && a.activity !== null && descends(a, call, agents))
      .sort((a, b) => (time(b.started_at) ?? 0) - (time(a.started_at) ?? 0));
    const member = inside[0];
    if (member?.activity != null) return member.activity;
  }
  return own?.activity ?? own?.description ?? "Working";
}

/** A pixie's own chat opens on its page; a project chat in its project. */
function placeOf(snapshot: IslandSnapshot, session: string, approvals: Approval[]): IslandPlace {
  const owner = snapshot.pixies.find((p) => p.chat_session_id === session);
  if (owner !== undefined) return { pixieChat: session, pixie: owner.id };
  const repo = snapshot.chats[session]?.repo ?? approvals[0]?.repo ?? null;
  if (repo?.startsWith("pixie:") === true) {
    return { pixieChat: session, pixie: repo.slice("pixie:".length) };
  }
  return { chat: session, repo };
}

function groupEntry(
  snapshot: IslandSnapshot,
  blocking: Approval[],
  session: string,
  group: GroupEntry,
): IslandEntry | null {
  const latest = group.calls[0];
  if (latest === undefined) return null;
  let figure: IslandFigure;
  let label: string;
  let key: string;
  if (group.kind === "team") {
    const team = snapshot.teams.find((t) => t.id === group.team_id);
    if (team === undefined) return null;
    figure = { team, members: group.members };
    label = team.name;
    key = `team:${team.id}`;
  } else {
    const pixie = snapshot.pixies.find((p) => p.id === group.pixie_id);
    if (pixie === undefined) return null;
    figure = { pixie };
    label = pixie.name;
    key = `pixie:${pixie.id}`;
  }
  const calls = new Set(group.calls.map((c) => c.tool_use_id));
  const approvals = blocking.filter((a) => {
    const call = a.payload.call;
    return typeof call === "string" && calls.has(call);
  });
  const started = Date.parse(latest.started_at);
  const state = standing(
    snapshot,
    session,
    approvals,
    group.state,
    time(latest.finished_at) ?? started,
    started,
  );
  if (state === null) return null;
  return {
    id: `${session}/${key}`,
    figure,
    label,
    place: placeOf(snapshot, session, approvals),
    approvalId: state.approval?.id ?? null,
    status: state.status,
    since: state.since,
    activity:
      state.status === "working"
        ? workingActivity(snapshot, session, latest.tool_use_id, group.kind === "team")
        : state.activity,
  };
}

const RUN_STATES: Partial<Record<HabitRun["outcome"], string>> = {
  running: "running",
  reported: "done",
  quiet: "done",
  failed: "failed",
  stalled: "failed",
  timed_out: "failed",
};

function habitEntry(
  snapshot: IslandSnapshot,
  blocking: Approval[],
  run: HabitRun,
): IslandEntry | null {
  const session = run.session_id;
  const pixie = snapshot.pixies.find((p) => p.id === run.pixie_id);
  const callState = RUN_STATES[run.outcome];
  if (session === null || pixie === undefined || callState === undefined) return null;
  const approvals = blocking.filter((a) => a.session_id === session);
  const started = time(run.started_at) ?? time(run.due_at) ?? snapshot.installedAt;
  const state = standing(
    snapshot,
    session,
    approvals,
    callState,
    time(run.ended_at) ?? started,
    started,
  );
  if (state === null) return null;
  const main = (snapshot.agents[session] ?? []).find((a) => a.parent == null)?.activity;
  return {
    id: `habit:${session}`,
    figure: { pixie },
    label: pixie.name,
    place: { habitRun: session },
    approvalId: state.approval?.id ?? null,
    status: state.status,
    since: state.since,
    activity: state.status === "working" ? (main ?? "Working") : state.activity,
  };
}

/** Newest first sorts by `since` descending, oldest first ascending; ties by id. */
function sorted(entries: IslandEntry[], order: IslandOrder): IslandEntry[] {
  return [...entries].sort((a, b) => {
    if (a.since !== b.since) return order === "newest" ? b.since - a.since : a.since - b.since;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

function nightshade(snapshot: IslandSnapshot): Nightshade {
  const normal = Object.values(snapshot.chats).filter((c) => c.normal);
  if (normal.some((c) => c.working)) return "working";
  const calls = Object.values(snapshot.groups).flatMap((groups) => groups.flatMap((g) => g.calls));
  // A call waiting on the user still runs.
  if (
    calls.some((c) => c.state === "running") ||
    snapshot.habitRuns.some((r) => r.outcome === "running")
  ) {
    return "idle";
  }
  const last = [
    ...normal.map((c) => c.updatedAt),
    ...(snapshot.awakeSince === null ? [] : [snapshot.awakeSince]),
    ...calls.map((c) => time(c.finished_at) ?? Date.parse(c.started_at)),
    ...snapshot.habitRuns.flatMap((r) => {
      const at = time(r.ended_at) ?? time(r.started_at);
      return at === null ? [] : [at];
    }),
  ];
  if (last.length === 0) return "asleep";
  return snapshot.now - Math.max(...last) >= SLEEP_AFTER_MS ? "asleep" : "idle";
}

// Show the island switched off: nothing at all, and the pill window hides.
export const HIDDEN: IslandState = {
  left: [],
  right: [],
  list: [],
  nightshade: null,
  restingBluebell: false,
};

export function islandState(snapshot: IslandSnapshot): IslandState {
  if (!snapshot.shown) return HIDDEN;
  const blocking = snapshot.approvals.filter((a) => BLOCKING.has(a.kind));
  const entries: IslandEntry[] = [];
  for (const [session, groups] of Object.entries(snapshot.groups)) {
    for (const group of groups) {
      const made = groupEntry(snapshot, blocking, session, group);
      if (made !== null) entries.push(made);
    }
  }
  for (const run of snapshot.habitRuns) {
    const made = habitEntry(snapshot, blocking, run);
    if (made !== null) entries.push(made);
  }
  const list = sorted(entries, snapshot.order);
  const left = list.filter((e) => e.status === "working");
  return {
    left,
    right: list.filter((e) => e.status !== "working"),
    list,
    nightshade: left.length === 0 ? nightshade(snapshot) : null,
    restingBluebell: entries.length === 0,
  };
}

/**
 * What a click lands on: Nightshade, the resting Bluebell or the empty strip (and the
 * list's "Nothing running" row); a pixie or its row; or a side's +N.
 */
export type IslandTarget = { strip: true } | { entry: IslandEntry } | { more: true };

/** What a click does, as IslandLayout.swift's IslandAction. */
export type IslandAction =
  | { openNest: true }
  | { open: IslandPlace }
  // The chat with the approval in view: the activity panel open on Needs you.
  | { openApproval: IslandPlace; approval: string }
  // The hover list, kept open until the pointer leaves.
  | { showList: true };

export function islandAction(target: IslandTarget): IslandAction {
  if ("strip" in target) return { openNest: true };
  if ("more" in target) return { showList: true };
  const { entry } = target;
  if (entry.approvalId !== null && (entry.status === "needsYou" || entry.status === "seen")) {
    return { openApproval: entry.place, approval: entry.approvalId };
  }
  return { open: entry.place };
}

/** The chat a click opens, which it marks seen: a done pixie leaves, needs you calms. */
export function seenChat(action: IslandAction): string | null {
  if ("open" in action) return placeSession(action.open);
  if ("openApproval" in action) return placeSession(action.openApproval);
  return null;
}

// The hover list shows this many rows and scrolls the rest (IslandScene.swift).
export const LIST_ROWS = 5;

/** The list's rows on screen: at least one, Nightshade's "Nothing running" when empty. */
export function listRows(state: IslandState): number {
  return Math.min(LIST_ROWS, Math.max(1, state.list.length));
}
