// Ported from NestKitTests/IslandTests.swift (B114): what the pixie pill shows, which side,
// until when, and when Nightshade works or sleeps.
import { describe, expect, it } from "vitest";
import type { Approval, CallState, GroupEntry, HabitRun, TrackedAgent } from "../api/types.ts";
import { approval, callEntry, habitRun, pixie, team, trackedAgent } from "../test/fixtures.ts";
import {
  HIDDEN,
  islandAction,
  islandState,
  listRows,
  seenChat,
  type IslandChat,
  type IslandSnapshot,
} from "./island.ts";

const t0 = Date.parse("2027-01-15T08:00:00Z");
const at = (minutes: number) => t0 + minutes * 60_000;
const iso = (minutes: number) => new Date(at(minutes)).toISOString();

const call = (
  tool: string,
  state: CallState,
  started: number,
  finished: number | null = null,
  pixieId = "p1",
) =>
  callEntry({
    id: `c-${tool}`,
    pixie_id: pixieId,
    tool_use_id: tool,
    state,
    started_at: iso(started),
    finished_at: finished === null ? null : iso(finished),
  });

const solo = (pixieId: string, ...calls: ReturnType<typeof call>[]): GroupEntry => ({
  kind: "pixie",
  pixie_id: pixieId,
  team_id: null,
  state: calls[0]?.state ?? "done",
  members: [],
  calls,
});

const ask = (id: string, created: number, extra: Partial<Approval> = {}, callId?: string) =>
  approval({
    id,
    created_at: iso(created),
    payload: {
      tool: "Bash",
      input: { command: "npm install" },
      ...(callId === undefined ? {} : { call: callId }),
    },
    ...extra,
  });

const agent = (id: string, extra: Partial<TrackedAgent> = {}) =>
  trackedAgent({ id, activity: null, description: null, parent: null, ...extra });

const chat = (working = false, updated = 0, normal = true): IslandChat => ({
  repo: "todo-ui",
  working,
  updatedAt: at(updated),
  normal,
});

const pixies = [
  pixie({ id: "p1", name: "Brook" }),
  pixie({ id: "p2", name: "Moth" }),
  pixie({ id: "p3", name: "P3" }),
];

function snapshot(overrides: Partial<IslandSnapshot> = {}): IslandSnapshot {
  return {
    groups: {},
    agents: {},
    approvals: [],
    habitRuns: [],
    pixies,
    teams: [],
    chats: {},
    seen: {},
    installedAt: t0,
    order: "newest",
    shown: true,
    now: at(10),
    awakeSince: null,
    ...overrides,
  };
}

const run = (session: string, outcome: HabitRun["outcome"], started: number, ended?: number) =>
  habitRun({
    id: `r-${session}`,
    habit_id: `h-${session}`,
    pixie_id: session === "hs2" ? "p2" : "p1",
    session_id: session,
    started_at: iso(started),
    due_at: iso(started),
    ended_at: ended === undefined ? null : iso(ended),
    outcome,
  });

describe("the pixie pill", () => {
  // B117 VM check: a chat called two pixies in the same second and one asked to write a
  // file. As the Mac's Builder.entries: every pixie of every chat's group is an entry.
  it("shows two pixies called at once in one chat, each on its own side", () => {
    const state = islandState(
      snapshot({
        groups: {
          s1: [
            solo("p1", call("tu1", "running", 1)),
            solo("p2", call("tu2", "running", 1, null, "p2")),
          ],
        },
        approvals: [ask("a1", 2, {}, "tu1")],
      }),
    );
    expect(state.left.map((e) => e.label)).toEqual(["Moth"]);
    expect(state.right.map((e) => [e.label, e.status])).toEqual([["Brook", "needsYou"]]);
    expect(state.nightshade).toBeNull();
  });

  it("shows working pixies on the left with what they do, newest first", () => {
    const state = islandState(
      snapshot({
        groups: {
          s1: [
            solo("p1", call("tu1", "running", 1)),
            solo("p2", call("tu2", "running", 2, null, "p2")),
            solo("p3", call("tu3", "running", 3, null, "p3")),
          ],
        },
        agents: {
          s1: [
            agent("tu1", { activity: "Editing auth.ts" }),
            agent("tu2", { description: "Fix the parser" }),
          ],
        },
        chats: { s1: chat(true) },
      }),
    );
    expect(state.left.map((e) => e.id)).toEqual(["s1/pixie:p3", "s1/pixie:p2", "s1/pixie:p1"]);
    expect(state.left.map((e) => e.activity)).toEqual([
      "Working",
      "Fix the parser",
      "Editing auth.ts",
    ]);
    expect(state.left[2]?.place).toEqual({ chat: "s1", repo: "todo-ui" });
    expect(state.right).toEqual([]);
    expect(state.nightshade).toBeNull();
  });

  it("needs the user when an approval names the call; a normal chat's never shows", () => {
    const state = islandState(
      snapshot({
        groups: {
          s1: [
            solo("p1", call("tu1", "running", 1)),
            {
              kind: "team",
              pixie_id: null,
              team_id: "t1",
              state: "running",
              members: [
                { pixie_id: "p2", leader: true, state: "running" },
                { pixie_id: "p3", leader: false, state: "running" },
              ],
              calls: [call("tu-lead", "running", 2, null, "p2")],
            },
          ],
        },
        approvals: [ask("a1", 4, {}, "tu-lead"), ask("a2", 5, { session_id: "s2" })],
        chats: { s1: chat(true), s2: chat(true) },
        teams: [team({ id: "t1", name: "Docs team", leader_id: "p2" })],
      }),
    );
    expect(state.left.map((e) => e.id)).toEqual(["s1/pixie:p1"]);
    expect(state.right).toHaveLength(1);
    expect(state.right[0]).toMatchObject({
      id: "s1/team:t1",
      status: "needsYou",
      approvalId: "a1",
      label: "Docs team",
      since: at(4),
    });
    expect(state.right[0]?.activity).toContain("npm install");
  });

  it("says what a working team's newest running member does", () => {
    const state = islandState(
      snapshot({
        groups: {
          s1: [
            {
              kind: "team",
              pixie_id: null,
              team_id: "t1",
              state: "running",
              members: [],
              calls: [call("tu-lead", "running", 2, null, "p2")],
            },
          ],
        },
        agents: {
          s1: [
            agent("tu-lead", { activity: "Planning" }),
            agent("m1", { parent: "tu-lead", activity: "Reading", started_at: iso(3) }),
            agent("m2", { parent: "m1", activity: "Rewriting the README", started_at: iso(4) }),
            agent("other", { activity: "Elsewhere", started_at: iso(5) }),
          ],
        },
        teams: [team({ id: "t1", name: "Docs team", leader_id: "p2" })],
      }),
    );
    expect(state.left.map((e) => e.activity)).toEqual(["Rewriting the README"]);
  });

  it("calms needs you once the chat is seen, until a newer approval", () => {
    const groups = { s1: [solo("p1", call("tu1", "running", 1))] };
    const calm = islandState(
      snapshot({ groups, approvals: [ask("a1", 2, {}, "tu1")], seen: { s1: at(3) } }),
    );
    expect(calm.right.map((e) => [e.status, e.since, e.approvalId])).toEqual([
      ["seen", at(3), "a1"],
    ]);
    expect(calm.nightshade).toBe("idle");
    const again = islandState(
      snapshot({
        groups,
        approvals: [ask("a1", 2, {}, "tu1"), ask("a2", 4, {}, "tu1")],
        seen: { s1: at(3) },
      }),
    );
    expect(again.right.map((e) => [e.status, e.approvalId])).toEqual([["needsYou", "a2"]]);
  });

  it("shows finished calls until seen, never those from before it first showed", () => {
    const groups = {
      s1: [solo("p1", call("tu1", "done", 1, 5)), solo("p2", call("tu2", "failed", 1, 4, "p2"))],
      s2: [
        solo("p3", call("tu3", "interrupted", 1, 3, "p3")),
        solo("p1", call("old", "done", -9, -1)),
      ],
    };
    const fresh = islandState(snapshot({ groups }));
    expect(fresh.right.map((e) => [e.id, e.status, e.activity])).toEqual([
      ["s1/pixie:p1", "done", "Finished"],
      ["s1/pixie:p2", "failed", "Failed"],
      ["s2/pixie:p3", "interrupted", "Interrupted"],
    ]);
    expect(islandState(snapshot({ groups, seen: { s1: at(6) } })).right.map((e) => e.id)).toEqual([
      "s2/pixie:p3",
    ]);
    // Finished after the chat was seen: it shows again.
    expect(islandState(snapshot({ groups, seen: { s1: at(4.5) } })).right.map((e) => e.id)).toEqual(
      ["s1/pixie:p1", "s2/pixie:p3"],
    );
  });

  it("moves Nightshade for normal chats only, and it sleeps after two quiet minutes", () => {
    expect(islandState(snapshot({ chats: { s1: chat(true) } })).nightshade).toBe("working");
    expect(islandState(snapshot({ chats: { hs: chat(true, 0, false) } })).nightshade).toBe(
      "asleep",
    );
    expect(islandState(snapshot({ chats: { s1: chat(false, 8.1) } })).nightshade).toBe("idle");
    expect(islandState(snapshot({ chats: { s1: chat(false, 7.9) } })).nightshade).toBe("asleep");
    expect(islandState(snapshot({ awakeSince: at(8.1) })).nightshade).toBe("idle");
    expect(islandState(snapshot({ awakeSince: at(7.9) })).nightshade).toBe("asleep");
  });

  it("rests Bluebell only while nothing shows", () => {
    expect(islandState(snapshot()).restingBluebell).toBe(true);
    const busy = islandState(snapshot({ groups: { s1: [solo("p1", call("tu1", "running", 1))] } }));
    expect(busy.restingBluebell).toBe(false);
  });

  it("shows habit runs like called pixies, never queued ones", () => {
    const running = run("hs1", "running", 1);
    const state = islandState(
      snapshot({
        agents: { hs1: [agent("main", { activity: "Checking pull requests" })] },
        habitRuns: [running, run("hs2", "queued", 2)],
      }),
    );
    expect(state.left.map((e) => [e.id, e.activity, e.label])).toEqual([
      ["habit:hs1", "Checking pull requests", "Brook"],
    ]);
    expect(state.left[0]?.place).toEqual({ habitRun: "hs1" });
    const asking = islandState(
      snapshot({
        approvals: [
          ask("a1", 3, { session_id: "hs1", kind: "question" }),
          ask("a2", 4, { session_id: "hs1", kind: "review" }),
        ],
        habitRuns: [running],
      }),
    );
    expect(asking.right.map((e) => [e.status, e.approvalId])).toEqual([["needsYou", "a1"]]);
    const ended = islandState(
      snapshot({ habitRuns: [run("hs1", "reported", 1, 4), run("hs2", "timed_out", 1, 5)] }),
    );
    expect(ended.right.map((e) => e.status)).toEqual(["failed", "done"]);
  });

  it("opens a call made in a pixie's own chat on that pixie", () => {
    const state = islandState(
      snapshot({
        groups: { pc1: [solo("p2", call("tu1", "running", 1, null, "p2"))] },
        pixies: [pixie({ id: "p1", name: "Brook", chat_session_id: "pc1" }), pixie({ id: "p2" })],
      }),
    );
    expect(state.left[0]?.place).toEqual({ pixieChat: "pc1", pixie: "p1" });
  });

  it("orders by the time of each state, newest or oldest first, ties by id", () => {
    const groups = {
      s1: [
        solo("p1", call("tu1", "running", 1)),
        solo("p2", call("tu2", "running", 3, null, "p2")),
        solo("p3", call("tu3", "done", 0, 2, "p3")),
      ],
      s2: [solo("p1", call("tu4", "running", 3))],
    };
    const approvals = [ask("a1", 6, { session_id: "s2" }, "tu4")];
    const newest = islandState(snapshot({ groups, approvals }));
    expect(newest.list.map((e) => e.id)).toEqual([
      "s2/pixie:p1",
      "s1/pixie:p2",
      "s1/pixie:p3",
      "s1/pixie:p1",
    ]);
    expect(newest.right.map((e) => e.id)).toEqual(["s2/pixie:p1", "s1/pixie:p3"]);
    const oldest = islandState(snapshot({ groups, approvals, order: "oldest" }));
    expect(oldest.list.map((e) => e.id)).toEqual([
      "s1/pixie:p1",
      "s1/pixie:p3",
      "s1/pixie:p2",
      "s2/pixie:p1",
    ]);
  });

  it("shows nothing at all while the island is switched off", () => {
    const groups = { s1: [solo("p1", call("tu1", "running", 1))] };
    expect(islandState(snapshot({ groups, shown: false }))).toEqual(HIDDEN);
  });
});

// Ported from IslandLayout.swift's IslandAction: what a click on the pill does.
describe("a click on the pill", () => {
  const groups = { s1: [solo("p1", call("tu1", "running", 1))] };

  it("opens Nest from Nightshade, Bluebell or the empty strip, and the list from +N", () => {
    expect(islandAction({ strip: true })).toEqual({ openNest: true });
    expect(islandAction({ more: true })).toEqual({ showList: true });
    expect(seenChat({ openNest: true })).toBeNull();
  });

  it("opens a pixie's chat, marking it seen", () => {
    const [entry] = islandState(snapshot({ groups })).left;
    if (entry === undefined) throw new Error("a working pixie shows");
    const action = islandAction({ entry });
    expect(action).toEqual({ open: { chat: "s1", repo: null } });
    expect(seenChat(action)).toBe("s1");
  });

  it("opens one that needs the user with its approval in view, calm or not", () => {
    const asking = islandState(snapshot({ groups, approvals: [ask("a1", 2, {}, "tu1")] }));
    const [entry] = asking.right;
    if (entry === undefined) throw new Error("a pixie that needs the user shows");
    expect(islandAction({ entry })).toEqual({
      openApproval: { chat: "s1", repo: "todo-ui" },
      approval: "a1",
    });
    const calm = islandState(
      snapshot({ groups, approvals: [ask("a1", 2, {}, "tu1")], seen: { s1: at(3) } }),
    ).right[0];
    if (calm === undefined) throw new Error("a seen one still shows");
    expect(islandAction({ entry: calm })).toMatchObject({ approval: "a1" });
  });

  it("lists at least one row on hover, Nightshade's when nothing runs, five at most", () => {
    expect(listRows(islandState(snapshot()))).toBe(1);
    const many = {
      s1: ["p1", "p2", "p3"].flatMap((p, i) => [
        solo(p, call(`a${String(i)}`, "running", i, null, p)),
      ]),
      s2: ["p1", "p2", "p3"].flatMap((p, i) => [
        solo(p, call(`b${String(i)}`, "running", i, null, p)),
      ]),
    };
    expect(listRows(islandState(snapshot({ groups: many })))).toBe(5);
  });
});
