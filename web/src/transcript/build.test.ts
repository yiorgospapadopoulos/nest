import { describe, expect, it } from "vitest";
import type { Approval, JsonObject } from "../api/types.ts";
import { approval, event, mergeApproval, plan, question, review } from "../test/fixtures.ts";
import { buildTranscript, resultSummary } from "./build.ts";

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
      { kind: "assistant", key: "2.1", text: "Reading." },
      {
        kind: "tool",
        key: "2.3",
        name: "Read",
        arg: "a.ts",
        result: "2 lines",
        detail: "line 1\nline 2",
        failed: false,
      },
      {
        kind: "tool",
        key: "2.4",
        name: "Bash",
        arg: "npm test",
        result: null,
        detail: null,
        failed: false,
      },
      {
        kind: "tool",
        key: "2.5",
        name: "Tool",
        arg: "",
        result: "failed",
        detail: "boom",
        failed: true,
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
      ],
      {},
      null,
    );

    expect(items).toEqual([
      { kind: "user", key: "1", text: "", attachments: [] },
      {
        kind: "tool",
        key: "4.0",
        name: "Tool",
        arg: "",
        result: "done",
        detail: null,
        failed: false,
      },
    ]);
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
