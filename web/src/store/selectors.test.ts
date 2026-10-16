import { describe, expect, it } from "vitest";
import type { BackgroundItem, Session } from "../api/types.ts";
import {
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
  team,
  NOW,
} from "../test/fixtures.ts";
import {
  type ChatEntry,
  chatLists,
  chatStatus,
  ciFailure,
  exchangeBackground,
  inboxGroups,
  isRunning,
  needsCount,
  nudgeText,
  unreadActions,
  pendingFor,
  availablePixies,
  availableTeams,
  chatTree,
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
  ])("%#: %s", (s, pending, tone, label) => {
    expect(chatStatus(s, pending)).toEqual({ tone, label });
  });
});

describe("chatLists", () => {
  it("groups a project's chats and keeps archived ones apart", () => {
    const sessions = [
      session({ id: "pin", pinned: true, updated_at: "2026-10-01T00:00:00Z" }),
      session({ id: "need" }),
      session({ id: "run", state: "running" }),
      session({ id: "idle", state: "failed", updated_at: "2026-10-05T00:00:00Z" }),
      session({ id: "idle2", updated_at: "2026-10-06T11:00:00Z" }),
      session({ id: "done", state: "closed" }),
      session({ id: "arch", archived_at: "2026-10-01T00:00:00Z" }),
      session({ id: "other", repo: "narrative" }),
    ];
    const lists = chatLists(state(sessions, [approval({ session_id: "need" })]), "cv-page");

    expect(lists.groups.map((g) => [g.group, g.chats.map(idOf)])).toEqual([
      ["pinned", ["pin"]],
      ["need", ["need"]],
      ["run", ["run"]],
      ["idle", ["idle2", "idle"]],
      ["done", ["done"]],
    ]);
    expect(lists.archived.map(idOf)).toEqual(["arch"]);
    expect(chatLists(state([]), "cv-page")).toEqual({ groups: [], archived: [] });
  });

  it("puts the project's Claude Code chats among the idle chats by time", () => {
    const s: State = {
      ...state([session({ id: "s1", updated_at: "2026-10-05T00:00:00Z" })], []),
      claudeChats: {
        new: claudeChat({ id: "new", last_activity_at: "2026-10-06T00:00:00Z" }),
        old: claudeChat({ id: "old", last_activity_at: "2026-10-04T00:00:00Z" }),
        else: claudeChat({ id: "else", repo: "narrative" }),
      },
    };

    const lists = chatLists(s, "cv-page");

    expect(lists.groups.map((g) => [g.group, g.chats.map(idOf)])).toEqual([
      ["idle", ["cc:new", "s1", "cc:old"]],
    ]);
    expect(lists.groups[0]?.chats[0]?.status).toEqual({ tone: "idle", label: "Claude Code" });
  });

  it("files archived Claude Code chats with the archived chats", () => {
    const s: State = {
      ...state([session({ id: "s1", updated_at: "2026-10-05T00:00:00Z", archived_at: "x" })], []),
      claudeChats: {
        done: claudeChat({ id: "done", archived: true, last_activity_at: "2026-10-06T00:00:00Z" }),
        live: claudeChat({ id: "live" }),
      },
    };

    const lists = chatLists(s, "cv-page");

    expect(lists.groups.map((g) => [g.group, g.chats.map(idOf)])).toEqual([["idle", ["cc:live"]]]);
    expect(lists.archived.map(idOf)).toEqual(["cc:done", "s1"]);
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

describe("isRunning", () => {
  it("is true while a chat of the project runs or starts", () => {
    expect(isRunning(state([session({ state: "starting" })]), "cv-page")).toBe(true);
    expect(isRunning(state([session({ state: "running" })]), "cv-page")).toBe(true);
    expect(isRunning(state([session({ state: "running" })]), "narrative")).toBe(false);
    expect(isRunning(state([session()]), "cv-page")).toBe(false);
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
    const lists = chatLists(state([stuck, session({ id: "b", state: "running" })], []), "cv-page");

    expect(lists.groups.map((g) => [g.group, g.chats.map(idOf)])).toEqual([
      ["need", ["a"]],
      ["run", ["b"]],
    ]);
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
    const ids = chatLists(s, "narrative")
      .groups.flatMap((g) => g.chats)
      .map((e) => e.session?.id);
    expect(ids).toEqual(["s1"]);
    expect(stuckChats(s)).toEqual([]);
    expect(isRunning(s, "narrative")).toBe(false);
    expect(inboxGroups(s).flatMap((g) => g.stuck)).toEqual([]);
  });

  it("treats a session without pixie_id as a project chat", () => {
    const old = { ...session({ id: "o", repo: "narrative" }) } as Partial<Session>;
    delete old.pixie_id;
    const s = state([old as Session]);
    expect(chatLists(s, "narrative").groups).toHaveLength(1);
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
        pixie({ id: "cv", slug: "cv", position: 5, projects: ["cv-page"], team_id: "docs" }),
        pixie({ id: "any", slug: "any", position: 0, projects: null }),
        pixie({ id: "read", slug: "read", position: 6, project_access: "read", projects: [] }),
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

  it("offers pixies that may work on the project, by position", () => {
    expect(availablePixies(withTeams(), "narrative").map((p) => p.id)).toEqual([
      "any",
      "bugs",
      "lead",
    ]);
    expect(availablePixies(withTeams(), "cv-page").map((p) => p.id)).toEqual([
      "any",
      "bugs",
      "lead",
      "cv",
    ]);
  });

  it("offers teams whose leader is available, with their available members", () => {
    const offered = (repo: string) =>
      availableTeams(withTeams(), repo).map(({ team: t, members }) => [
        t.id,
        members.map((m) => m.id),
      ]);
    expect(offered("narrative")).toEqual([["qa", ["bugs", "lead"]]]);
    expect(offered("cv-page")).toEqual([
      ["qa", ["bugs", "lead"]],
      ["docs", ["cv"]],
    ]);
  });

  it("offers alone only the pixies in no team the chat can call (B46)", () => {
    expect(soloPixies(withTeams(), "narrative").map((p) => p.id)).toEqual(["any"]);
    // "cv" leads docs, which a chat in cv-page can call.
    expect(soloPixies(withTeams(), "cv-page").map((p) => p.id)).toEqual(["any"]);
    // A team whose leader cannot work here leaves its members callable alone.
    const leaderless: State = {
      ...withTeams(),
      teams: { qa: team({ id: "qa", handle: "qa", leader_id: "blind" }) },
    };
    expect(soloPixies(leaderless, "narrative").map((p) => p.id)).toEqual(["any", "bugs", "lead"]);
  });

  it("says why a message calling a team's pixie alone cannot be sent (B46)", () => {
    const state = withTeams();
    const said = (text: string, repo = "narrative") => memberCall(state, repo, text);
    expect(said("@bugs look")).toBe("Tester is in @qa; call the team or a solo copy");
    expect(said("ask @qa and @lead, please")).toBe(
      "Tester is in @qa; call the team or a solo copy",
    );
    expect(said("@qa look at @any")).toBeNull();
    // Not a whole token, or a pixie the chat cannot call.
    expect(said("mail me@bugs or @bugs-x")).toBeNull();
    expect(said("@cv")).toBeNull();
    expect(said("@cv", "cv-page")).toBe("Tester is in @docs; call the team or a solo copy");
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
