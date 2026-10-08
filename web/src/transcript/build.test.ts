import { describe, expect, it } from "vitest";
import type { Approval, JsonObject } from "../api/types.ts";
import { approval, event, mergeApproval, plan, question, review } from "../test/fixtures.ts";
import { buildTranscript, resultSummary, turnStart } from "./build.ts";

const json = (a: Approval) => ({ ...a }) as unknown as JsonObject;

describe("buildTranscript", () => {
  it("renders user messages, assistant text and tool calls with their results", () => {
    const items = buildTranscript(
      [
        event({
          id: 1,
          type: "session.user_message",
          payload: { text: "Fix it", attachments: [{ filename: "a.png" }, {}] },
        }),
        event({
          id: 2,
          type: "session.message",
          payload: {
            parent_tool_use_id: null,
            blocks: [
              { type: "thinking", text: "hmm" },
              { type: "text", text: "Reading." },
              { type: "text", text: "  " },
              { type: "tool_use", id: "t1", name: "Read", input: { file_path: "/w/s1/a.ts" } },
              { type: "tool_use", name: "Bash", input: { command: "npm test" } },
              { type: "tool_use", id: "t3", input: {} },
            ],
          },
        }),
        event({
          id: 3,
          type: "session.message",
          payload: {
            blocks: [
              { type: "tool_result", tool_use_id: "t1", content: "line 1\nline 2" },
              { type: "tool_result", tool_use_id: "t3", content: "boom", is_error: true },
              { type: "tool_result", tool_use_id: "missing", content: "x" },
            ],
          },
        }),
        event({
          id: 4,
          type: "session.message",
          payload: { parent_tool_use_id: "t9", blocks: [{ type: "text", text: "sub" }] },
        }),
      ],
      {},
      "/w/s1",
    );

    expect(items).toEqual([
      { kind: "user", key: "1", text: "Fix it", attachments: ["a.png", "file"] },
      { kind: "thinking", key: "2.0", text: "hmm", ms: null },
      { kind: "assistant", key: "2.1", text: "Reading." },
      {
        kind: "tools",
        key: "2.3",
        items: [
          {
            kind: "tool",
            key: "2.3",
            id: "t1",
            name: "Read",
            arg: "a.ts",
            result: "2 lines",
            detail: "line 1\nline 2",
            failed: false,
          },
          {
            kind: "tool",
            key: "2.4",
            id: "2.4",
            name: "Bash",
            arg: "npm test",
            result: null,
            detail: null,
            failed: false,
          },
          {
            kind: "tool",
            key: "2.5",
            id: "t3",
            name: "Tool",
            arg: "",
            result: "failed",
            detail: "boom",
            failed: true,
          },
        ],
      },
    ]);
  });

  it("shows pending approvals inline and finished ones as notes", () => {
    const resolved = (a: Approval, resolution: JsonObject, status: Approval["status"]) =>
      event({
        id: 90,
        type: "approval.resolved",
        payload: { approval: json({ ...a, status, resolution }) },
      });
    const created = (a: Approval, id: number) =>
      event({ id, type: "approval.created", payload: { approval: json(a) } });
    const allowed = approval({ id: "p1" });
    const denied = approval({ id: "p2" });
    const answered = question({ id: "a1" });
    const dismissed = question({ id: "a2" });
    const merged = review({ id: "r1" });
    const committed = review({ id: "r2" });
    const rejected = review({ id: "r3" });
    const expired = approval({ id: "e1" });
    const superseded = review({ id: "x1" });
    const pending = approval({ id: "live" });

    const items = buildTranscript(
      [
        created(pending, 1),
        created(allowed, 2),
        created(denied, 3),
        created(answered, 4),
        created(dismissed, 5),
        created(merged, 6),
        created(committed, 7),
        created(rejected, 8),
        created(expired, 9),
        created(superseded, 10),
        created(approval({ id: "unknown" }), 11),
        resolved(allowed, { behavior: "allow" }, "resolved"),
        resolved(denied, { behavior: "deny" }, "resolved"),
        resolved(answered, { answers: { "DAG or tree?": "DAG" } }, "resolved"),
        resolved(dismissed, { dismissed: true }, "resolved"),
        resolved(merged, { action: "approved", pr_url: "https://pr" }, "resolved"),
        resolved(committed, { action: "approved", pr_url: null }, "resolved"),
        resolved(rejected, { action: "rejected" }, "resolved"),
        resolved(expired, { reason: "x" }, "expired"),
        resolved(superseded, {}, "superseded"),
        event({
          id: 91,
          type: "approval.resolved",
          payload: {
            approval: json({ ...review({ id: "r9" }), status: "resolved", resolution: null }),
          },
        }),
        created(review({ id: "r9" }), 92),
      ],
      { live: pending },
      null,
    );

    expect(items).toEqual([
      { kind: "approval", key: "1", approval: pending },
      { kind: "system", key: "2", text: "Allowed: npm install zod" },
      { kind: "system", key: "3", text: "Rejected: npm install zod" },
      { kind: "system", key: "4", text: "Answered: DAG" },
      { kind: "system", key: "5", text: "Question dismissed" },
      { kind: "system", key: "6", text: "Approved. Pull request opened" },
      { kind: "system", key: "7", text: "Approved and committed" },
      { kind: "system", key: "8", text: "Rejected. Nothing merged" },
      { kind: "system", key: "9", text: "Request expired" },
      { kind: "system", key: "92", text: "Approved and committed" },
    ]);
  });

  it("leaves a merge to its own line and notes a dismissed one", () => {
    const decided = (id: string, resolution: JsonObject, at: number) => [
      event({
        id: at,
        type: "approval.created",
        payload: { approval: json(mergeApproval({ id })) },
      }),
      event({
        id: at + 1,
        type: "approval.resolved",
        payload: { approval: json({ ...mergeApproval({ id }), status: "resolved", resolution }) },
      }),
    ];

    const items = buildTranscript(
      [
        ...decided("m1", { action: "merged", method: "squash" }, 1),
        ...decided("m2", { dismissed: true }, 3),
      ],
      {},
      null,
    );

    expect(items).toEqual([{ kind: "system", key: "3", text: "Merge dismissed" }]);
  });

  it("shows a pending plan inline and notes how finished plans went", () => {
    const pending = plan({ id: "live" });
    const decided = (id: string, resolution: JsonObject, at: number) => [
      event({ id: at, type: "approval.created", payload: { approval: json(plan({ id })) } }),
      event({
        id: at + 1,
        type: "approval.resolved",
        payload: { approval: json({ ...plan({ id }), status: "resolved", resolution }) },
      }),
    ];

    const items = buildTranscript(
      [
        ...decided("p1", { decision: "approve" }, 1),
        ...decided("p2", { decision: "keep_planning", message: "Smaller steps" }, 3),
        ...decided("p3", { decision: "keep_planning", message: null }, 5),
        event({ id: 7, type: "approval.created", payload: { approval: json(pending) } }),
      ],
      { live: pending },
      null,
    );

    expect(items).toEqual([
      { kind: "system", key: "1", text: "Plan approved" },
      { kind: "system", key: "3", text: "Keep planning: Smaller steps" },
      { kind: "system", key: "5", text: "Keep planning" },
      { kind: "approval", key: "7", approval: pending },
    ]);
  });

  it("notes interruptions, failures and git steps", () => {
    const items = buildTranscript(
      [
        event({ id: 1, type: "session.state", payload: { state: "running" } }),
        event({ id: 2, type: "session.state", payload: { state: "interrupted" } }),
        event({ id: 3, type: "session.state", payload: { state: "failed", error: "boom" } }),
        event({ id: 4, type: "session.state", payload: { state: "failed", error: null } }),
        event({ id: 5, type: "session.result", payload: { is_error: true } }),
        event({ id: 6, type: "session.result", payload: { is_error: false } }),
        event({ id: 7, type: "session.setup_failed", payload: { command: "npm ci" } }),
        event({ id: 8, type: "session.setup_failed", payload: {} }),
        event({ id: 9, type: "session.git_violation", payload: {} }),
        event({ id: 10, type: "git.failed", payload: { step: "push" } }),
        event({ id: 11, type: "git.failed", payload: {} }),
        event({ id: 12, type: "pr.opened", payload: { url: "u" } }),
        event({ id: 13, type: "session.tasks", payload: {} }),
        event({ id: 14, type: "pr.merged", payload: { url: "u", method: "rebase" } }),
        event({ id: 15, type: "pr.merged", payload: { url: "u" } }),
        event({ id: 16, type: "session.pr", payload: { pr: {} } }),
      ],
      {},
      null,
    );

    expect(items.map((i) => (i.kind === "system" ? i.text : i.kind))).toEqual([
      "Interrupted",
      "Failed: boom",
      "Failed",
      "The turn ended with an error",
      "Setup failed: npm ci",
      "Setup failed: ",
      "The agent changed git refs itself",
      "Git push failed",
      "Git  failed",
      "Pull request opened",
      "Pull request merged (rebase)",
      "Pull request merged (squash)",
    ]);
  });

  it("tolerates messages without text or blocks", () => {
    const items = buildTranscript(
      [
        event({ id: 1, type: "session.user_message", payload: {} }),
        event({ id: 2, type: "session.message", payload: { blocks: [{ type: "text" }] } }),
        event({ id: 3, type: "session.message", payload: {} }),
        event({
          id: 4,
          type: "session.message",
          payload: {
            blocks: [
              { type: "tool_use", id: "t" },
              { type: "tool_result", tool_use_id: "t" },
            ],
          },
        }),
        event({ id: 5, type: "session.message", payload: { blocks: [{ type: "tool_result" }] } }),
        event({
          id: 6,
          type: "session.message",
          payload: { blocks: [{ type: "image" }, { type: "thinking" }] },
        }),
      ],
      {},
      null,
    );

    expect(items).toEqual([
      { kind: "user", key: "1", text: "", attachments: [] },
      {
        kind: "tool",
        key: "4.0",
        id: "t",
        name: "Tool",
        arg: "",
        result: "done",
        detail: null,
        failed: false,
      },
      { kind: "thinking", key: "6.1", text: "", ms: null },
    ]);
  });
});

const blocks = (id: number, ...list: JsonObject[]) =>
  event({ id, type: "session.message", payload: { parent_tool_use_id: null, blocks: list } });
const call = (id: string, name = "Bash") => ({ type: "tool_use", id, name, input: {} });
const done = (id: string) => ({ type: "tool_result", tool_use_id: id, content: "ok" });
const shape = (items: ReturnType<typeof buildTranscript>) =>
  items.map((i) =>
    i.kind === "tools" ? `group:${i.items.map((c) => c.key).join(",")}` : `${i.kind}:${i.key}`,
  );

describe("thinking", () => {
  it("shows the main agent's thinking with how long it took", () => {
    const items = buildTranscript(
      [
        blocks(1, { type: "thinking", text: "Plan the fix", duration_ms: 8200 }),
        blocks(2, { type: "thinking", text: "" }),
        event({
          id: 3,
          type: "session.message",
          payload: { parent_tool_use_id: "a1", blocks: [{ type: "thinking", text: "sub" }] },
        }),
      ],
      {},
      null,
    );

    expect(items).toEqual([
      { kind: "thinking", key: "1.0", text: "Plan the fix", ms: 8200 },
      { kind: "thinking", key: "2.0", text: "", ms: null },
    ]);
  });
});

describe("tool groups", () => {
  it("groups consecutive calls, with the thinking between them, until text breaks the run", () => {
    const thought = { type: "thinking", text: "next" };
    const items = buildTranscript(
      [
        blocks(1, thought, call("a"), thought, call("b"), done("a")),
        blocks(2, done("b"), thought),
        blocks(3, { type: "text", text: "Now the edit." }, call("c", "Edit")),
        blocks(4, { type: "tool_use", id: "x", name: "TaskCreate", input: {} }, call("d")),
        blocks(5, { type: "text", text: "Done." }),
      ],
      {},
      null,
    );

    expect(shape(items)).toEqual([
      "thinking:1.0",
      "group:1.1,1.2,1.3",
      "thinking:2.1",
      "assistant:3.0",
      // Hidden task list calls do not show, so they do not split a group either.
      "group:3.1,4.1",
      "assistant:5.0",
    ]);
  });

  it("leaves a single call as a plain row", () => {
    const items = buildTranscript([blocks(1, call("a"), { type: "text", text: "ok" })], {}, null);

    expect(shape(items)).toEqual(["tool:1.0", "assistant:1.1"]);
  });
});

describe("turn lines", () => {
  const user = (id: number) => event({ id, type: "session.user_message", payload: { text: "go" } });
  const state = (id: number, payload: JsonObject) => event({ id, type: "session.state", payload });
  const result = (id: number, ms?: number) =>
    event({
      id,
      type: "session.result",
      payload: ms === undefined ? { is_error: false } : { is_error: false, duration_ms: ms },
    });
  const texts = (items: ReturnType<typeof buildTranscript>) =>
    items.map((i) => (i.kind === "turn" || i.kind === "system" ? `${i.kind}:${i.text}` : i.kind));

  it("ends each turn with how long it worked, or ran before it stopped", () => {
    const items = buildTranscript(
      [
        user(1),
        state(2, { state: "running", turn_start: true }),
        result(3, 70_000),
        state(4, { state: "idle", error: null, duration_ms: 72_400 }),
        user(5),
        state(6, { state: "interrupted", error: null, duration_ms: 40_000 }),
        user(7),
        state(8, { state: "failed", error: "boom", duration_ms: 5_000 }),
      ],
      {},
      null,
    );

    expect(texts(items)).toEqual([
      "user",
      "turn:Worked for 1m 12s",
      "user",
      "turn:Stopped after 40s",
      "user",
      "system:Failed: boom",
      "turn:Stopped after 5s",
    ]);
    expect(items.filter((i) => i.kind === "turn").map((i) => i.key)).toEqual([
      "4.end",
      "6.end",
      "8.end",
    ]);
  });

  it("times a turn a queued message ends, and older turns, by the engine's result", () => {
    const items = buildTranscript(
      [
        user(1),
        result(2, 3_000),
        user(3),
        state(4, { state: "running", turn_start: true }),
        result(5, 9_000),
        state(6, { state: "interrupted" }),
        user(7),
        result(8, 1_000),
        state(9, { state: "idle", duration_ms: null }),
      ],
      {},
      null,
    );

    expect(texts(items)).toEqual([
      "user",
      "turn:Worked for 3s",
      "user",
      "turn:Stopped after 9s",
      "user",
      "turn:Worked for 1s",
    ]);
    expect(items[1]?.key).toBe("2.end");
  });

  it("keeps the plain notes when nothing says how long a turn took", () => {
    const items = buildTranscript(
      [
        user(1),
        result(2),
        state(3, { state: "interrupted", error: null }),
        user(4),
        state(5, { state: "failed", error: null, duration_ms: null }),
        state(6, { state: "idle" }),
        user(7),
        result(8),
        user(9),
      ],
      {},
      null,
    );

    expect(texts(items)).toEqual([
      "user",
      "system:Interrupted",
      "user",
      "system:Failed",
      "user",
      "user",
    ]);
  });
});

describe("error turns", () => {
  const user = (id: number) => event({ id, type: "session.user_message", payload: { text: "go" } });
  const texts = (items: ReturnType<typeof buildTranscript>) =>
    items.map((i) => (i.kind === "turn" || i.kind === "system" ? `${i.kind}:${i.text}` : i.kind));

  it("say why the turn failed, once, when its state carries the reason", () => {
    const items = buildTranscript(
      [
        user(1),
        event({ id: 2, type: "session.state", payload: { state: "running", turn_start: true } }),
        event({ id: 3, type: "session.result", payload: { is_error: true, duration_ms: 4_000 } }),
        event({
          id: 4,
          type: "session.state",
          payload: { state: "failed", error: "Usage limit reached", duration_ms: 5_000 },
        }),
      ],
      {},
      null,
    );

    expect(texts(items)).toEqual([
      "user",
      "system:Failed: Usage limit reached",
      "turn:Stopped after 5s",
    ]);
  });

  it("keep older error turns, which ended idle, readable", () => {
    const items = buildTranscript(
      [
        user(1),
        event({ id: 2, type: "session.result", payload: { is_error: true, duration_ms: 4_000 } }),
        event({ id: 3, type: "session.state", payload: { state: "idle", duration_ms: 5_000 } }),
      ],
      {},
      null,
    );

    expect(texts(items)).toEqual([
      "user",
      "system:The turn ended with an error",
      "turn:Worked for 5s",
    ]);
  });
});

describe("tool calls of a turn that ended", () => {
  // A daemon restart cut the turn off: interrupted, with neither call's result.
  const cutOff = [
    event({ id: 1, type: "session.user_message", payload: { text: "go" } }),
    blocks(2, call("a")),
    blocks(3, call("b")),
    event({ id: 4, type: "session.state", payload: { state: "interrupted" } }),
  ];
  const tools = (items: ReturnType<typeof buildTranscript>) =>
    items.flatMap((i) => (i.kind === "tools" ? i.items : [i])).filter((i) => i.kind === "tool");

  it("stop running", () => {
    const items = buildTranscript(cutOff, {}, null);

    expect(tools(items).map((t) => t.result)).toEqual(["stopped", "stopped"]);
    // A single call too, and one a new message follows instead of a turn end.
    const single = buildTranscript(
      [blocks(1, call("a")), event({ id: 2, type: "session.user_message", payload: {} })],
      {},
      null,
    );
    expect(tools(single).map((t) => t.result)).toEqual(["stopped"]);
  });

  it("keep running while the background task they started runs, and keep a late result", () => {
    const items = buildTranscript(
      [...cutOff, blocks(5, { type: "tool_result", tool_use_id: "b", content: "late" })],
      {},
      null,
      new Set(["a"]),
    );

    expect(tools(items).map((t) => t.result)).toEqual([null, "late"]);
  });

  it("run on while the turn is open", () => {
    const items = buildTranscript(cutOff.slice(0, 3), {}, null);

    expect(tools(items).map((t) => t.result)).toEqual([null, null]);
  });
});

describe("notices", () => {
  it("show the engine's notices as notes", () => {
    const notice = (id: number, payload: JsonObject) =>
      event({ id, type: "session.notice", payload });
    const items = buildTranscript(
      [
        notice(1, { kind: "compacted", text: "Conversation compacted" }),
        notice(2, { kind: "api_retry", text: "Claude's API is busy. Retrying" }),
        notice(3, { kind: "cleared" }),
      ],
      {},
      null,
    );

    expect(items).toEqual([
      { kind: "system", key: "1", text: "Conversation compacted" },
      { kind: "system", key: "2", text: "Claude's API is busy. Retrying" },
    ]);
  });
});

describe("turnStart", () => {
  const at = (id: number, type: string, payload: JsonObject = {}) =>
    event({ id, type, payload, ts: `2026-01-01T12:00:0${String(id)}Z` });

  it("is when the running turn started, by its mark or else its message", () => {
    expect(turnStart([])).toBeNull();
    expect(turnStart([at(1, "session.state", { state: "starting" })])).toBeNull();
    expect(turnStart([at(1, "session.user_message"), at(2, "session.message")])).toBe(
      "2026-01-01T12:00:01Z",
    );
    expect(
      turnStart([
        at(1, "session.user_message"),
        at(2, "session.state", { state: "running", turn_start: true }),
        at(3, "session.state", { state: "waiting" }),
        at(4, "session.state", { state: "running" }),
      ]),
    ).toBe("2026-01-01T12:00:02Z");
  });

  it("is null once the turn ended", () => {
    for (const state of ["idle", "interrupted", "failed", "closed"]) {
      expect(
        turnStart([at(1, "session.user_message"), at(2, "session.state", { state })]),
      ).toBeNull();
    }
  });
});

describe("resultSummary", () => {
  it("summarises tool output in a few words", () => {
    expect(resultSummary("ok", false)).toBe("ok");
    expect(resultSummary("x".repeat(60), false)).toBe(`${"x".repeat(39)}…`);
    expect(resultSummary("\n\n", false)).toBe("done");
    expect(resultSummary("a\nb\n\nc", false)).toBe("3 lines");
    expect(resultSummary("a", true)).toBe("failed");
  });
});
