import { describe, expect, it } from "vitest";
import type { BackgroundItem, Session } from "../api/types.ts";
import {
  approval,
  check,
  event,
  claudeChat,
  mergeApproval,
  plan,
  prStatus,
  question,
  repo,
  review,
  session,
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
  pendingFor,
  stuckChats,
} from "./selectors.ts";
import { initialState, type State } from "./state.ts";

function state(sessions: Session[], approvals = [approval()]): State {
  return {
    ...initialState,
    repos: [repo("narwhal"), repo("todo-ui")],
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
      session({ id: "other", repo: "narwhal" }),
    ];
    const lists = chatLists(state(sessions, [approval({ session_id: "need" })]), "todo-ui");

    expect(lists.groups.map((g) => [g.group, g.chats.map(idOf)])).toEqual([
      ["pinned", ["pin"]],
      ["need", ["need"]],
      ["run", ["run"]],
      ["idle", ["idle2", "idle"]],
      ["done", ["done"]],
    ]);
    expect(lists.archived.map(idOf)).toEqual(["arch"]);
    expect(chatLists(state([]), "todo-ui")).toEqual({ groups: [], archived: [] });
  });

  it("puts the project's Claude Code chats among the idle chats by time", () => {
    const s: State = {
      ...state([session({ id: "s1", updated_at: "2026-10-05T00:00:00Z" })], []),
      claudeChats: {
        new: claudeChat({ id: "new", last_activity_at: "2026-10-06T00:00:00Z" }),
        old: claudeChat({ id: "old", last_activity_at: "2026-10-04T00:00:00Z" }),
        else: claudeChat({ id: "else", repo: "narwhal" }),
      },
    };

    const lists = chatLists(s, "todo-ui");

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

    const lists = chatLists(s, "todo-ui");

    expect(lists.groups.map((g) => [g.group, g.chats.map(idOf)])).toEqual([["idle", ["cc:live"]]]);
    expect(lists.archived.map(idOf)).toEqual(["cc:done", "s1"]);
  });
});

describe("inbox", () => {
  it("groups pending items by project in project order, unknown projects last", () => {
    const items = [
      approval({ id: "a", repo: "todo-ui", created_at: "2026-10-06T10:00:02Z" }),
      approval({ id: "b", repo: "narwhal" }),
      approval({ id: "c", repo: "todo-ui", created_at: "2026-10-06T10:00:01Z" }),
      approval({ id: "d", repo: "zeta" }),
      approval({ id: "e", repo: "alpha" }),
    ];
    const s = state([], items);

    expect(inboxGroups(s).map((g) => [g.repo, g.items.map((a) => a.id)])).toEqual([
      ["narwhal", ["b"]],
      ["todo-ui", ["c", "a"]],
      ["alpha", ["e"]],
      ["zeta", ["d"]],
    ]);
    expect(needsCount(s)).toBe(5);
    expect(needsCount(s, "todo-ui")).toBe(2);
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
        failed("late", "todo-ui", "2026-10-06T11:00:00Z"),
        failed("early", "todo-ui", "2026-10-06T09:00:00Z"),
        failed("ci", "ci-only", NOW),
        session({ id: "green", pr: prStatus() }),
      ],
      [approval({ id: "a", repo: "todo-ui" })],
    );

    expect(
      inboxGroups(s).map((g) => [
        g.repo,
        g.items.map((a) => a.id),
        g.failures.map((f) => f.session.id),
      ]),
    ).toEqual([
      ["todo-ui", ["a"], ["early", "late"]],
      ["ci-only", [], ["ci"]],
    ]);
    expect(needsCount(s)).toBe(4);
    expect(needsCount(s, "todo-ui")).toBe(3);
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
    expect(isRunning(state([session({ state: "starting" })]), "todo-ui")).toBe(true);
    expect(isRunning(state([session({ state: "running" })]), "todo-ui")).toBe(true);
    expect(isRunning(state([session({ state: "running" })]), "narwhal")).toBe(false);
    expect(isRunning(state([session()]), "todo-ui")).toBe(false);
  });
});

describe("ciFailure", () => {
  const failing = prStatus({
    checks: [check("unit", "failure"), check("lint"), check("e2e", "failure")],
  });

  it("names the failing checks of an idle chat's open pull request", () => {
    expect(ciFailure(session({ pr: failing }), [])).toEqual({
      repo: "todo-ui",
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
    const lists = chatLists(state([stuck, session({ id: "b", state: "running" })], []), "todo-ui");

    expect(lists.groups.map((g) => [g.group, g.chats.map(idOf)])).toEqual([
      ["need", ["a"]],
      ["run", ["b"]],
    ]);
  });

  it("list unarchived stuck chats, longest stuck first, in the inbox and its counts", () => {
    const later = session({ id: "a", stuck: flag("2026-10-06T10:05:00Z") });
    const earlier = session({ id: "b", repo: "narwhal", stuck: flag("2026-10-06T09:00:00Z") });
    const shelved = session({ id: "c", stuck: flag(NOW), archived_at: NOW });
    const s = state([later, earlier, shelved, session({ id: "d" })], []);

    expect(stuckChats(s).map((x) => x.session.id)).toEqual(["b", "a"]);
    expect(inboxGroups(s).map((g) => [g.repo, g.stuck.map((x) => x.session.id)])).toEqual([
      // Projects in their listed order.
      ["narwhal", ["b"]],
      ["todo-ui", ["a"]],
    ]);
    expect(needsCount(s)).toBe(2);
    expect(needsCount(s, "narwhal")).toBe(1);
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
