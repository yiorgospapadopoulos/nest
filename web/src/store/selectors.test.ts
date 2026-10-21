import { describe, expect, it } from "vitest";
import type { BackgroundItem, ModelOption, Session } from "../api/types.ts";
import {
  account,
  agentDefaults,
  claudeProvider,
  codexProvider,
  modelList,
  models,
  approval,
  check,
  event,
  claudeChat,
  callEntry,
  groupEntry,
  trackedAgent,
  pixie,
  mergeApproval,
  plan,
  prStatus,
  question,
  report,
  repo,
  review,
  session,
  task,
  team,
  NOW,
  NO_BACKGROUND,
} from "../test/fixtures.ts";
import {
  type ChatEntry,
  CLAUDE_CHAT_STATUS,
  catalogFor,
  chatGroup,
  chatList,
  chatModel,
  engineDetail,
  engineList,
  engineName,
  lastActivity,
  modelSections,
  modelTitle,
  newChatDefaults,
  offersEngineChoice,
  signInHint,
  supportsFeature,
  usageBarChoices,
  usageBarLines,
  chatStatus,
  ciFailure,
  exchangeBackground,
  inboxGroups,
  needsCount,
  nudgeText,
  unreadActions,
  unreadReports,
  pendingFor,
  availablePixies,
  availableTeams,
  chatTree,
  goalEntries,
  memberCall,
  soloPixies,
  pixieList,
  pixieWorking,
  stuckChats,
  teamList,
} from "./selectors.ts";
import { initialState, type State } from "./state.ts";

function state(sessions: Session[], approvals = [approval()]): State {
  return {
    ...initialState,
    repos: [repo("narrative"), repo("cv-page")],
    sessions: Object.fromEntries(sessions.map((s) => [s.id, s])),
    approvals: Object.fromEntries(approvals.map((a) => [a.id, a])),
  };
}

const idOf = (entry: ChatEntry) =>
  entry.session === undefined ? `cc:${entry.chat.id}` : entry.session.id;

const PAUSE = {
  window: "five_hour" as const,
  resets_at: "2026-10-06T14:00:00Z",
  resume_at: "2026-10-06T14:00:30Z",
  since: NOW,
};

describe("chatStatus", () => {
  it.each([
    [session(), [question()], "wait", "Question"],
    [session({ state: "waiting" }), [plan(), approval()], "wait", "Plan ready"],
    [session(), [approval()], "wait", "Needs approval"],
    [session({ state: "waiting" }), [], "wait", "Needs approval"],
    [session({ state: "starting" }), [], "run", "Starting"],
    [session({ state: "running" }), [], "run", "Running"],
    [session({ state: "failed" }), [], "fail", "Failed"],
    [session({ state: "interrupted" }), [], "int", "Interrupted"],
    [session({ state: "closed" }), [], "done", "Done"],
    [session(), [review()], "rev", "Ready for review"],
    [session(), [mergeApproval()], "rev", "Ready to merge"],
    [session(), [review(), mergeApproval()], "rev", "Ready for review"],
    [session(), [], "idle", "Idle"],
    // A chat paused at a usage limit goes on by itself (B78); a review still comes first.
    [session({ limit_pause: PAUSE }), [], "int", "Paused"],
    [session({ limit_pause: PAUSE }), [review()], "rev", "Ready for review"],
    [session({ limit_pause: PAUSE }), [question()], "wait", "Question"],
  ])("%#: %s", (s, pending, tone, label) => {
    expect(chatStatus(s, pending)).toEqual({ tone, label });
  });
});

describe("goalEntries (B47)", () => {
  const tracked = (s: State, tasks: Record<string, ReturnType<typeof task>[]>): State => ({
    ...s,
    tracking: Object.fromEntries(
      Object.entries(tasks).map(([id, list]) => [
        id,
        { tasks: list, agents: [], background: NO_BACKGROUND },
      ]),
    ),
  });

  it("lists working chats first, then chats with tasks, each newest first", () => {
    const s = tracked(
      state(
        [
          session({ id: "old", updated_at: "2026-10-01T00:00:00Z" }),
          session({ id: "new", state: "closed", updated_at: "2026-10-05T00:00:00Z" }),
          session({ id: "run", state: "running", updated_at: "2026-10-02T00:00:00Z" }),
          session({ id: "wait", state: "waiting", updated_at: "2026-10-03T00:00:00Z" }),
          session({ id: "start", state: "starting", updated_at: "2026-10-04T00:00:00Z" }),
        ],
        [],
      ),
      { old: [task()], new: [task({ status: "completed" })] },
    );

    expect(goalEntries(s, "cv-page").map((g) => g.session.id)).toEqual([
      "start",
      "wait",
      "run",
      "new",
      "old",
    ]);
    const run = goalEntries(s, "cv-page")[2];
    expect(run?.tasks).toEqual([]);
    expect(run?.status).toEqual({ tone: "run", label: "Running" });
  });

  it("leaves out idle chats without tasks, deleted tasks, archived, pixie and other chats", () => {
    const s = tracked(
      state(
        [
          session({ id: "quiet" }),
          session({ id: "gone" }),
          session({ id: "kept" }),
          session({ id: "shelved", state: "running", archived_at: "2026-10-01T00:00:00Z" }),
          session({ id: "pix", state: "running", pixie_id: "p1" }),
          session({ id: "else", state: "running", repo: "narrative" }),
        ],
        [],
      ),
      {
        gone: [task({ status: "deleted" })],
        kept: [task({ id: "1", status: "deleted" }), task({ id: "2" })],
        shelved: [task()],
      },
    );

    const entries = goalEntries(s, "cv-page");

    expect(entries.map((g) => g.session.id)).toEqual(["kept"]);
    expect(entries[0]?.tasks.map((t) => t.id)).toEqual(["2"]);
    expect(goalEntries(state([]), "cv-page")).toEqual([]);
  });
});

describe("inbox", () => {
  it("groups pending items by project in project order, unknown projects last", () => {
    const items = [
      approval({ id: "a", repo: "cv-page", created_at: "2026-10-06T10:00:02Z" }),
      approval({ id: "b", repo: "narrative" }),
      approval({ id: "c", repo: "cv-page", created_at: "2026-10-06T10:00:01Z" }),
      approval({ id: "d", repo: "zeta" }),
      approval({ id: "e", repo: "alpha" }),
    ];
    const s = state([], items);

    expect(inboxGroups(s).map((g) => [g.repo, g.items.map((a) => a.id)])).toEqual([
      ["narrative", ["b"]],
      ["cv-page", ["c", "a"]],
      ["alpha", ["e"]],
      ["zeta", ["d"]],
    ]);
    expect(needsCount(s)).toBe(5);
    expect(needsCount(s, "cv-page")).toBe(2);
  });

  it("adds unread warn and action reports under their pixie, newest first (B42)", () => {
    const s: State = {
      ...state([], [approval({ id: "a", repo: "pixie:p1" })]),
      reports: Object.fromEntries(
        [
          report({ id: "old", created_at: "2026-10-14T07:00:00Z" }),
          report({ id: "new", severity: "warn", created_at: "2026-10-14T08:00:00Z" }),
          report({ id: "info", severity: "info" }),
          report({ id: "read", read_at: NOW }),
          report({ id: "other", pixie_id: "p2" }),
        ].map((r) => [r.id, r]),
      ),
    };

    expect(inboxGroups(s).map((g) => [g.repo, g.items.length, g.reports.map((r) => r.id)])).toEqual(
      [
        ["pixie:p1", 1, ["new", "old"]],
        ["pixie:p2", 0, ["other"]],
      ],
    );
    expect(needsCount(s)).toBe(4);
    expect(needsCount(s, "pixie:p2")).toBe(1);
    // Only unread action reports count on the pixie.
    expect(unreadActions(s, "p1")).toBe(1);
    expect(unreadActions(s, "p3")).toBe(0);
    expect(unreadActions(s)).toBe(2);
    // The Pixies view lists the same reports, newest first (B102).
    expect(unreadReports(s).map((r) => r.id)).toEqual(["new", "other", "old"]);
  });

  it("adds open pull requests whose checks failed, oldest change first", () => {
    const failed = (id: string, repoName: string, changed: string) =>
      session({
        id,
        repo: repoName,
        pr: prStatus({ checks: [check("unit", "failure")], changed_at: changed }),
      });
    const s = state(
      [
        failed("late", "cv-page", "2026-10-06T11:00:00Z"),
        failed("early", "cv-page", "2026-10-06T09:00:00Z"),
        failed("ci", "ci-only", NOW),
        session({ id: "green", pr: prStatus() }),
      ],
      [approval({ id: "a", repo: "cv-page" })],
    );

    expect(
      inboxGroups(s).map((g) => [
        g.repo,
        g.items.map((a) => a.id),
        g.failures.map((f) => f.session.id),
      ]),
    ).toEqual([
      ["cv-page", ["a"], ["early", "late"]],
      ["ci-only", [], ["ci"]],
    ]);
    expect(needsCount(s)).toBe(4);
    expect(needsCount(s, "cv-page")).toBe(3);
  });

  it("lists a session's pending items oldest first", () => {
    const s = state(
      [session()],
      [
        approval({ id: "late", created_at: "2026-10-06T11:00:00Z" }),
        approval({ id: "early", created_at: "2026-10-06T09:00:00Z" }),
        approval({ id: "x", session_id: "s2" }),
      ],
    );

    expect(pendingFor(s, "s1").map((a) => a.id)).toEqual(["early", "late"]);
  });
});

describe("ciFailure", () => {
  const failing = prStatus({
    checks: [check("unit", "failure"), check("lint"), check("e2e", "failure")],
  });

  it("names the failing checks of an idle chat's open pull request", () => {
    expect(ciFailure(session({ pr: failing }), [])).toEqual({
      repo: "cv-page",
      session: session({ pr: failing }),
      pr: failing,
      names: ["unit", "e2e"],
    });
    expect(ciFailure(session({ state: "failed", pr: failing }), [approval()])?.names).toEqual([
      "unit",
      "e2e",
    ]);
  });

  it.each([
    ["no pull request", session(), []],
    ["passing checks", session({ pr: prStatus() }), []],
    ["merged", session({ pr: { ...failing, state: "merged" as const } }), []],
    ["the agent is working", session({ state: "running", pr: failing }), []],
    ["the chat is closed", session({ state: "closed", pr: failing }), []],
    ["archived", session({ archived_at: NOW, pr: failing }), []],
    ["a fix waits for review", session({ pr: failing }), [review()]],
  ])("is nothing with %s", (_, s, pending) => {
    expect(ciFailure(s, pending)).toBeNull();
  });
});

describe("stuck chats", () => {
  const flag = (since: string, details = "Stuck") => ({
    reason: "silent" as const,
    since,
    details,
  });

  it("group a stuck chat with the ones that need the user", () => {
    const stuck = session({ id: "a", state: "running", stuck: flag(NOW) });
    const running = session({ id: "b", state: "running" });

    expect(chatGroup(stuck, chatStatus(stuck, []))).toBe("need");
    expect(chatGroup(running, chatStatus(running, []))).toBe("run");
  });

  it("list unarchived stuck chats, longest stuck first, in the inbox and its counts", () => {
    const later = session({ id: "a", stuck: flag("2026-10-06T10:05:00Z") });
    const earlier = session({ id: "b", repo: "narrative", stuck: flag("2026-10-06T09:00:00Z") });
    const shelved = session({ id: "c", stuck: flag(NOW), archived_at: NOW });
    const s = state([later, earlier, shelved, session({ id: "d" })], []);

    expect(stuckChats(s).map((x) => x.session.id)).toEqual(["b", "a"]);
    expect(inboxGroups(s).map((g) => [g.repo, g.stuck.map((x) => x.session.id)])).toEqual([
      // Projects in their listed order.
      ["narrative", ["b"]],
      ["cv-page", ["a"]],
    ]);
    expect(needsCount(s)).toBe(2);
    expect(needsCount(s, "narrative")).toBe(1);
  });

  it("word the nudge from the reason", () => {
    expect(nudgeText("No new output for 12 minutes.")).toBe(
      "You seem stuck: no new output for 12 minutes. Step back and try a different approach.",
    );
    expect(nudgeText("Called Bash 5 times in a row with the same input")).toBe(
      "You seem stuck: called Bash 5 times in a row with the same input. " +
        "Step back and try a different approach.",
    );
  });
});

describe("the background bar's exchange", () => {
  const item = (id: string, status: BackgroundItem["status"], started: string | null) => ({
    id,
    kind: "agent" as const,
    name: "Explore",
    description: null,
    status,
    started_at: started,
    finished_at: null,
  });
  // An earlier turn's task, then three of the turn the latest message opened.
  const summary = {
    running: 3,
    completed: 3,
    items: [
      item("old", "done", "2026-10-06T09:00:10Z"),
      item("still", "running", "2026-10-06T09:00:20Z"),
      item("unknown", "failed", null),
      item("a", "done", "2026-10-06T10:00:00+00:00"),
      item("b", "running", "2026-10-06T10:00:05Z"),
      item("c", "running", "2026-10-06T10:00:06Z"),
    ],
  };
  const message = (id: number, ts: string) =>
    event({ id, type: "session.user_message", ts, payload: { text: "go" } });

  it("keeps the tasks started since the user's latest message and any still running", () => {
    const events = [
      message(1, "2026-10-06T09:00:00Z"),
      message(2, "2026-10-06T10:00:00.000Z"),
      // The agent going on by itself stays in the exchange.
      event({ id: 3, type: "session.state", payload: { state: "running", turn_start: true } }),
    ];
    const current = exchangeBackground(summary, events);
    expect(current.items.map((i) => i.id)).toEqual(["still", "a", "b", "c"]);
    expect([current.running, current.completed]).toEqual([3, 1]);
  });

  it("starts from zero after the next message, and keeps everything without one", () => {
    const next = exchangeBackground(summary, [message(4, "2026-10-06T11:00:00Z")]);
    expect(next.items.map((i) => i.id)).toEqual(["still", "b", "c"]);
    expect([next.running, next.completed]).toEqual([3, 0]);

    expect(exchangeBackground(summary, undefined)).toBe(summary);
    expect(exchangeBackground(summary, [event({ type: "session.state" })])).toBe(summary);
  });

  it("places a task by the event that started it, whatever the clocks said (I-H)", () => {
    const call = (id: number, toolId: string) =>
      event({
        id,
        type: "session.message",
        payload: {
          parent_tool_use_id: null,
          blocks: [{ type: "tool_use", id: toolId, name: "Agent", input: {} }],
        },
      });
    const done = (id: string, started: string, finished: string) => ({
      ...item(id, "done", started),
      finished_at: finished,
    });
    const stepped = {
      running: 0,
      completed: 3,
      items: [
        // Started before the message, though its clock read later.
        done("before", "2026-10-06T10:10:00Z", "2026-10-06T09:59:00Z"),
        // Started after the message, though the clock had stepped back.
        done("after", "2026-10-06T09:50:00Z", "2026-10-06T09:55:00Z"),
        // No call in the transcript: its time decides.
        done("timed", "2026-10-06T10:01:00Z", "2026-10-06T10:02:00Z"),
      ],
    };
    const events = [call(3, "before"), message(5, "2026-10-06T10:00:00Z"), call(7, "after")];

    const current = exchangeBackground(stepped, events);
    expect(current.items.map((i) => i.id)).toEqual(["after", "timed"]);
  });

  it("counts a carried-over task that finishes as completed in the current exchange", () => {
    const finished = (id: string, started: string, at: string) => ({
      ...item(id, "done", started),
      finished_at: at,
    });
    const carried = {
      running: 0,
      completed: 3,
      items: [
        // Finished before the latest message: the earlier exchange's.
        finished("before", "2026-10-06T09:00:10Z", "2026-10-06T09:30:00Z"),
        // Ran into the latest exchange and finished there.
        finished("over", "2026-10-06T09:00:20Z", "2026-10-06T10:05:00Z"),
        {
          ...item("failed", "failed", "2026-10-06T09:00:30Z"),
          finished_at: "2026-10-06T10:06:00Z",
        },
      ],
    };

    const current = exchangeBackground(carried, [message(1, "2026-10-06T10:00:00Z")]);
    expect(current.items.map((i) => i.id)).toEqual(["over", "failed"]);
    expect([current.running, current.completed]).toEqual([0, 2]);
  });
});

describe("pixies", () => {
  const withPixies = (): State => ({
    ...state([
      session({ id: "s1", repo: "narrative" }),
      session({
        id: "s2",
        repo: "narrative",
        pixie_id: "a",
        state: "running",
        stuck: { reason: "silent", since: NOW, details: "No output." },
      }),
    ]),
    pixies: {
      b: pixie({ id: "b", position: 1 }),
      a: pixie({ id: "a", position: 0 }),
      h: pixie({ id: "h", position: 2, hidden: true }),
    },
  });

  it("lists visible pixies by position", () => {
    expect(pixieList(withPixies()).map((p) => p.id)).toEqual(["a", "b"]);
  });

  it("keeps pixie chats out of project lists, counts and the inbox", () => {
    const s = withPixies();
    const ids = chatList(s, "narrative").chats.map((e) => e.session?.id);
    expect(ids).toEqual(["s1"]);
    expect(stuckChats(s)).toEqual([]);
    expect(inboxGroups(s).flatMap((g) => g.stuck)).toEqual([]);
  });

  it("treats a session without pixie_id as a project chat", () => {
    const old = { ...session({ id: "o", repo: "narrative" }) } as Partial<Session>;
    delete old.pixie_id;
    const s = state([old as Session]);
    expect(chatList(s, "narrative").chats).toHaveLength(1);
  });
});

describe("teams and who a chat can call", () => {
  const withTeams = (): State => ({
    ...initialState,
    pixies: Object.fromEntries(
      [
        pixie({ id: "lead", slug: "lead", position: 3, team_id: "qa" }),
        pixie({ id: "bugs", slug: "bugs", position: 1, team_id: "qa" }),
        pixie({ id: "shy", slug: "shy", position: 2, team_id: "qa", hidden: true }),
        pixie({ id: "blind", slug: "blind", position: 4, project_access: "none" }),
        pixie({ id: "cv", slug: "cv", position: 5, team_id: "docs" }),
        pixie({ id: "any", slug: "any", position: 0 }),
        pixie({ id: "read", slug: "read", position: 6, project_access: "read" }),
      ].map((p) => [p.id, p]),
    ),
    teams: {
      docs: team({ id: "docs", handle: "docs", position: 1, leader_id: "cv" }),
      qa: team({ id: "qa", handle: "qa", position: 0, leader_id: "lead" }),
      empty: team({ id: "empty", handle: "empty", position: 2, leader_id: null }),
      gone: team({ id: "gone", handle: "gone", position: 3, leader_id: "missing" }),
    },
  });

  it("lists teams by position", () => {
    expect(teamList(withTeams()).map((t) => t.id)).toEqual(["qa", "docs", "empty", "gone"]);
  });

  it("offers in every project the pixies not hidden that may touch project files (B85)", () => {
    expect(availablePixies(withTeams()).map((p) => p.id)).toEqual([
      "any",
      "bugs",
      "lead",
      "cv",
      "read",
    ]);
  });

  it("offers teams whose leader is available, with their available members", () => {
    expect(
      availableTeams(withTeams()).map(({ team: t, members }) => [t.id, members.map((m) => m.id)]),
    ).toEqual([
      ["qa", ["bugs", "lead"]],
      ["docs", ["cv"]],
    ]);
  });

  it("offers alone only the pixies in no team the chat can call (B46)", () => {
    expect(soloPixies(withTeams()).map((p) => p.id)).toEqual(["any", "read"]);
    // A team whose leader cannot work in projects leaves its members callable alone.
    const leaderless: State = {
      ...withTeams(),
      teams: { qa: team({ id: "qa", handle: "qa", leader_id: "blind" }) },
    };
    expect(soloPixies(leaderless).map((p) => p.id)).toEqual(["any", "bugs", "lead", "cv", "read"]);
  });

  it("says why a message calling a team's pixie alone cannot be sent (B46)", () => {
    const state = withTeams();
    const said = (text: string) => memberCall(state, text);
    expect(said("@bugs look")).toBe("Tester is in @qa; call the team or a solo copy");
    expect(said("ask @qa and @lead, please")).toBe(
      "Tester is in @qa; call the team or a solo copy",
    );
    expect(said("@qa look at @any")).toBeNull();
    expect(said("@cv")).toBe("Tester is in @docs; call the team or a solo copy");
    // Not a whole token, or a pixie the chat cannot call.
    expect(said("mail me@bugs or @bugs-x")).toBeNull();
    expect(said("@blind")).toBeNull();
  });
});

describe("a chat's tree (B46)", () => {
  const state = (overrides: Partial<State> = {}): State => ({
    ...initialState,
    pixies: { p1: pixie({ id: "p1", slug: "scribe" }) },
    ...overrides,
  });

  it("is empty for a chat with no pixies or running subagents", () => {
    expect(chatTree(state(), "s1")).toEqual({ pixies: [], subagents: [] });
  });

  it("holds the chat's pixies and its running subagents, nested under their parents", () => {
    const old = trackedAgent({ id: "a9", name: "Old" });
    delete old.parent;
    const agents = [
      trackedAgent({ id: "main", name: "main" }),
      trackedAgent({ id: "a1" }),
      trackedAgent({ id: "a2", parent: "a1", name: "Plan" }),
      trackedAgent({ id: "a3", parent: "a2", name: "Deep" }),
      trackedAgent({ id: "a4", status: "done" }),
      // A pixie's call shows among the pixies, by its call or its slug.
      trackedAgent({ id: "a5", name: "anything" }),
      trackedAgent({ id: "a6", name: "scribe" }),
      // Started by a subagent no longer listed: shown at the top.
      trackedAgent({ id: "a7", parent: "a6", name: "Helper" }),
      trackedAgent({ id: "a8", parent: "a4", name: "Orphan" }),
      // Daemons before B46 name no parent.
      old,
    ];
    const tree = chatTree(
      state({
        pixieGroups: {
          s1: [
            groupEntry({
              calls: [callEntry({ tool_use_id: "x1" }), { ...callEntry(), tool_use_id: "a5" }],
            }),
          ],
        },
        tracking: {
          s1: { tasks: [], agents, background: { running: 0, completed: 0, items: [] } },
        },
      }),
      "s1",
    );
    expect(tree.pixies).toHaveLength(1);
    const shape = (nodes: typeof tree.subagents): unknown[] =>
      nodes.map((n) => [n.agent.id, shape(n.children)]);
    expect(shape(tree.subagents)).toEqual([
      ["a1", [["a2", [["a3", []]]]]],
      ["a7", []],
      ["a8", []],
      ["a9", []],
    ]);
  });
});

describe("whether a pixie is at work (B48)", () => {
  const scribe = pixie({ id: "p1", chat_session_id: "own" });
  const base = (overrides: Partial<State> = {}): State => ({
    ...initialState,
    pixies: { p1: scribe },
    ...overrides,
  });
  const member = (state: TeamMemberState) => ({ pixie_id: "p1", leader: false, state });
  type TeamMemberState = "running" | "done" | null;

  it("is at work while its own chat starts or runs", () => {
    for (const [chat, working] of [
      ["starting", true],
      ["running", true],
      ["waiting", false],
      ["idle", false],
    ] as const) {
      const sessions = { own: session({ id: "own", state: chat, pixie_id: "p1" }) };
      expect(pixieWorking(base({ sessions }), scribe)).toBe(working);
    }
    // Its chat not read yet, or none at all.
    expect(pixieWorking(base(), scribe)).toBe(false);
    expect(pixieWorking(base(), { ...scribe, chat_session_id: null })).toBe(false);
  });

  it("is at work while any chat's call of it runs, alone or with its team", () => {
    const solo = (state: "running" | "done", id = "p1") => groupEntry({ pixie_id: id, state });
    const crew = (state: TeamMemberState) =>
      groupEntry({ kind: "team", pixie_id: null, team_id: "t1", members: [member(state)] });
    expect(pixieWorking(base({ pixieGroups: { s1: [solo("done")] } }), scribe)).toBe(false);
    expect(pixieWorking(base({ pixieGroups: { s1: [solo("running", "p2")] } }), scribe)).toBe(
      false,
    );
    expect(
      pixieWorking(base({ pixieGroups: { s1: [solo("done")], s2: [solo("running")] } }), scribe),
    ).toBe(true);
    expect(pixieWorking(base({ pixieGroups: { s1: [crew(null), crew("done")] } }), scribe)).toBe(
      false,
    );
    expect(pixieWorking(base({ pixieGroups: { s1: [crew("running")] } }), scribe)).toBe(true);
  });
});

describe("chatList (B102 item 9, as the Mac's SidebarGroup.list)", () => {
  it("lists every chat by its latest activity, pinned ones above, archived apart", () => {
    const sessions = [
      session({ id: "pin-old", pinned: true, updated_at: "2026-10-01T00:00:00Z" }),
      session({ id: "pin-new", pinned: true, updated_at: "2026-10-03T00:00:00Z" }),
      session({ id: "waiting", state: "waiting", updated_at: "2026-10-02T00:00:00Z" }),
      session({ id: "running", state: "running", updated_at: "2026-10-05T00:00:00Z" }),
      session({ id: "done", state: "closed", updated_at: "2026-10-06T00:00:00Z" }),
      session({
        id: "arch",
        archived_at: "2026-10-01T00:00:00Z",
        pinned: true,
        updated_at: "2026-10-01T00:00:00Z",
      }),
      session({ id: "other", repo: "narrative" }),
      session({ id: "pixie", pixie_id: "p1" }),
    ];
    const s: State = {
      ...state(sessions, [approval({ session_id: "waiting" })]),
      claudeChats: {
        cc: claudeChat({ id: "cc", last_activity_at: "2026-10-04T00:00:00Z" }),
        gone: claudeChat({ id: "gone", archived: true, last_activity_at: "2026-10-05T00:00:00Z" }),
      },
    };

    const lists = chatList(s, "cv-page");

    expect(lists.pinned.map(idOf)).toEqual(["pin-new", "pin-old"]);
    expect(lists.chats.map(idOf)).toEqual(["done", "running", "cc:cc", "waiting"]);
    expect(lists.archived.map(idOf)).toEqual(["cc:gone", "arch"]);
    expect(lists.chats[3]?.status).toEqual({ tone: "wait", label: "Needs approval" });
    expect(lists.chats[2]?.status).toEqual(CLAUDE_CHAT_STATUS);
  });

  it("orders chats of the same moment by id, newest id first, as the Mac does", () => {
    const s = state([session({ id: "a" }), session({ id: "b" })], []);
    expect(chatList(s, "cv-page").chats.map(idOf)).toEqual(["b", "a"]);
  });

  it("is empty for a project without chats", () => {
    expect(chatList(state([]), "cv-page")).toEqual({ pinned: [], chats: [], archived: [] });
  });

  it("gives each row the time of its latest activity", () => {
    const chat = session({ updated_at: "2026-10-06T09:55:00Z" });
    const cc = claudeChat({ last_activity_at: "2026-10-05T09:00:00Z" });
    expect(lastActivity({ session: chat, status: CLAUDE_CHAT_STATUS })).toBe(chat.updated_at);
    expect(lastActivity({ chat: cc, status: CLAUDE_CHAT_STATUS })).toBe(cc.last_activity_at);
  });
});

describe("engines (B102 items 22, 25, 27, 28, as NestKit ProvidersStore)", () => {
  const gpt: ModelOption = {
    value: "gpt-5.5",
    display_name: "GPT-5.5",
    description: "Codex's best",
    effort_levels: ["low", "medium", "high"],
    supports_effort: true,
    supports_auto_mode: false,
    claude_code_effort: null,
  };

  function engines(overrides: Partial<State> = {}): State {
    return {
      ...initialState,
      providers: [claudeProvider(), codexProvider()],
      modelLists: {
        claude: modelList({ default_model: "opus" }),
        codex: modelList({ models: [gpt], default_model: "gpt-5.5" }),
      },
      ...overrides,
    };
  }

  it("lists the engines, Claude alone before the list loads", () => {
    expect(engineList(engines()).map((p) => p.name)).toEqual(["claude", "codex"]);
    const before = { ...initialState, account: account() };
    expect(engineList(before)).toEqual([
      {
        name: "claude",
        display_name: "Claude",
        signed_in: null,
        sign_in_hint: null,
        account: account(),
        unsupported: [],
      },
    ]);
    expect(offersEngineChoice(engines())).toBe(true);
    expect(offersEngineChoice(before)).toBe(false);
  });

  it("names an engine, an unknown one after itself, and none as Claude", () => {
    expect(engineName(engines(), "codex")).toBe("Codex");
    expect(engineName(engines(), null)).toBe("Claude");
    expect(engineName(initialState, "gemini")).toBe("Gemini");
  });

  it("says under an engine that it is not signed in, else its plan", () => {
    expect(engineDetail(codexProvider({ signed_in: false }))).toBe("Not signed in");
    expect(engineDetail(codexProvider())).toBe("ChatGPT Plus");
    expect(engineDetail(claudeProvider({ account: null }))).toBe("");
  });

  it("gives each engine's real models with its default model", () => {
    const claude = catalogFor(engines(), "claude");
    expect(claude.models.map((m) => m.value)).toEqual(["opus", "haiku", "claude-opus-4-6"]);
    expect(claude.defaultModel).toBe("opus");
    expect(catalogFor(engines(), null)).toEqual(claude);
    expect(catalogFor(engines(), "codex")).toEqual({ models: [gpt], defaultModel: "gpt-5.5" });
    expect(catalogFor(initialState, "codex")).toEqual({ models: [], defaultModel: null });
    // Before B102's lists loaded, Claude's old list stands in, without a default.
    const old = { ...initialState, models: models() };
    expect(catalogFor(old, "claude").models).toHaveLength(3);
    expect(catalogFor(old, "claude").defaultModel).toBeNull();
    expect(catalogFor(initialState, "claude")).toEqual({ models: [], defaultModel: null });
  });

  it("offers a new chat every engine, an open chat its own, one Model section alone", () => {
    const draft = modelSections(engines(), null, true);
    expect(draft.map((s) => [s.provider, s.title, s.detail])).toEqual([
      ["claude", "Claude", "Claude Max"],
      ["codex", "Codex", "ChatGPT Plus"],
    ]);
    expect(draft[1]?.catalog.models).toEqual([gpt]);
    const open = modelSections(engines(), "codex", false);
    expect(open.map((s) => s.provider)).toEqual(["codex"]);
    expect(modelSections(engines(), null, false).map((s) => s.provider)).toEqual(["claude"]);
    const alone = modelSections({ ...engines(), providers: [claudeProvider()] }, null, true);
    expect(alone.map((s) => [s.provider, s.title, s.detail])).toEqual([["claude", "Model", ""]]);
  });

  it("titles a model after its engine off Claude", () => {
    expect(modelTitle(engines(), "gpt-5.5", "codex")).toBe("Codex · GPT-5.5");
    expect(modelTitle(engines(), null, "codex")).toBe("Codex · GPT-5.5");
    expect(modelTitle(engines(), "haiku", "claude")).toBe("Haiku 4.5");
    expect(modelTitle(engines(), null, null)).toBe("Opus 5.5");
  });

  it("reads a chat without a model as its engine's default", () => {
    expect(chatModel(engines(), session({ model: "haiku" }))).toBe("haiku");
    expect(chatModel(engines(), session({ model: null }))).toBe("opus");
    expect(chatModel(engines(), session({ model: null, provider: "codex" }))).toBe("gpt-5.5");
  });

  it("knows what an engine's chats cannot do, offering everything when not listed", () => {
    expect(supportsFeature(engines(), "rewind", "codex")).toBe(false);
    expect(supportsFeature(engines(), "rewind", "claude")).toBe(true);
    expect(supportsFeature(engines(), "rewind", null)).toBe(true);
    expect(supportsFeature(initialState, "rewind", "codex")).toBe(true);
  });

  it("gives the sign-in hint only for an engine that said it is signed out", () => {
    const out = engines({
      providers: [
        claudeProvider(),
        codexProvider({ signed_in: false, sign_in_hint: "Sign in to Codex on the Mac" }),
      ],
    });
    expect(signInHint(out, "codex")).toBe("Sign in to Codex on the Mac");
    expect(signInHint(engines(), "codex")).toBeNull();
    expect(signInHint(out, "claude")).toBeNull();
    expect(signInHint(out, null)).toBeNull();
    const bare = engines({ providers: [claudeProvider(), codexProvider({ signed_in: false })] });
    expect(signInHint(bare, "codex")).toBe("Codex isn't signed in.");
  });

  it("starts a new chat's draft from the concrete agent defaults", () => {
    expect(newChatDefaults(engines())).toBeNull();
    const withDefaults = engines({
      agentDefaults: agentDefaults({ provider: "codex", model: null, effort: null }),
    });
    expect(newChatDefaults(withDefaults)).toEqual({
      provider: "codex",
      model: "gpt-5.5",
      effort: "medium",
      permission: "default",
    });
  });
});

describe("the usage bar's engines (B102 items 23, 29)", () => {
  function engines(overrides: Partial<State> = {}): State {
    return { ...initialState, providers: [claudeProvider(), codexProvider()], ...overrides };
  }

  it("shows Claude and every other engine signed in, in the list's order", () => {
    expect(usageBarLines(engines())).toEqual([
      { provider: "claude", name: "Claude" },
      { provider: "codex", name: "Codex" },
    ]);
    const out = engines({ providers: [claudeProvider(), codexProvider({ signed_in: null })] });
    expect(usageBarLines(out).map((l) => l.provider)).toEqual(["claude"]);
    expect(usageBarLines(initialState).map((l) => l.provider)).toEqual(["claude"]);
  });

  it("leaves out the engines unchecked on this device, keeping Claude when none is left", () => {
    expect(usageBarLines(engines({ usageBarHidden: ["claude"] })).map((l) => l.provider)).toEqual([
      "codex",
    ]);
    const none = engines({ usageBarHidden: ["claude", "codex"] });
    expect(usageBarLines(none).map((l) => l.provider)).toEqual(["claude"]);
  });

  it("lists a checkmark per engine, saying which are not signed in", () => {
    const out = engines({
      providers: [claudeProvider(), codexProvider({ signed_in: false })],
      usageBarHidden: ["claude"],
    });
    expect(usageBarChoices(out)).toEqual([
      { provider: "claude", name: "Claude", detail: "", shown: false },
      { provider: "codex", name: "Codex", detail: "Not signed in", shown: true },
    ]);
    expect(usageBarChoices(initialState)).toEqual([
      { provider: "claude", name: "Claude", detail: "", shown: true },
    ]);
  });
});
