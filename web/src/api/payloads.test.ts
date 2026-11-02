// @vitest-environment node
import { describe, expect, it } from "vitest";
import type { JsonValue } from "./types.ts";
import {
  approval,
  mergeApproval,
  plan,
  prStatus,
  question,
  queuedMessage,
  review,
} from "../test/fixtures.ts";
import { ApiError } from "./client.ts";
import {
  contextOf,
  localFailureOf,
  serverDownOf,
  mergeOf,
  num,
  permissionOf,
  planOf,
  prOf,
  queuedOf,
  questionsOf,
  reviewOf,
  str,
  stuckOf,
  toolArg,
} from "./payloads.ts";

describe("toolArg", () => {
  it("picks the most telling field and shortens paths", () => {
    expect(toolArg({ command: "npm test\nmore" }, null)).toBe("npm test");
    expect(toolArg({ file_path: "/w/s1/src/a.ts" }, "/w/s1")).toBe("src/a.ts");
    expect(toolArg({ file_path: "/w/s1/src/a.ts" }, "/w/s1/")).toBe("src/a.ts");
    expect(toolArg({ file_path: "/elsewhere/a.ts" }, "/w/s1")).toBe("/elsewhere/a.ts");
    expect(toolArg({ taskId: 4 }, null)).toBe("4");
    expect(toolArg({ pattern: "", description: "Find docs" }, null)).toBe("Find docs");
    expect(toolArg({ other: true }, null)).toBe("");
  });
});

describe("primitive readers", () => {
  it("fall back on the wrong type", () => {
    expect(str(3)).toBeNull();
    expect(num("3")).toBe(0);
  });
});

describe("permissionOf", () => {
  it("shows a Bash command with its description", () => {
    expect(permissionOf(approval(), null)).toEqual({
      tool: "Bash",
      command: "npm install zod",
      why: "Adds zod",
      reason: null,
      always: "Bash",
    });
  });

  it("shows other tools with their argument and the prompt title", () => {
    const item = approval({
      payload: {
        tool: "Edit",
        input: { file_path: "/w/s1/a.ts" },
        title: "Edit a file?",
        reason: "Outside the project",
        always_rule: "Edit(src/**)",
      },
    });

    expect(permissionOf(item, "/w/s1")).toEqual({
      tool: "Edit",
      command: "Edit a.ts",
      why: "Edit a file?",
      reason: "Outside the project",
      always: "Edit(src/**)",
    });
  });

  it("survives a malformed payload", () => {
    expect(
      permissionOf(approval({ payload: { input: [], reason: 4, always_rule: 5 } }), null),
    ).toEqual({
      tool: "Tool",
      command: "Tool",
      why: null,
      reason: null,
      always: "Tool",
    });
    expect(permissionOf(approval({ payload: { tool: "Bash", input: null } }), null).command).toBe(
      "",
    );
  });
});

describe("questionsOf", () => {
  it("reads questions and options", () => {
    expect(questionsOf(question())).toEqual([
      {
        question: "DAG or tree?",
        header: "Structure",
        multiSelect: false,
        options: [
          { label: "Tree", description: "Simple", recommended: false },
          { label: "DAG", description: "Shares lines", recommended: true },
        ],
      },
    ]);
  });

  it("tolerates missing fields", () => {
    const item = question({ payload: { questions: [{ multi_select: true, options: [{}] }] } });

    expect(questionsOf(item)).toEqual([
      {
        question: "",
        header: null,
        multiSelect: true,
        options: [{ label: "", description: null, recommended: false }],
      },
    ]);
    expect(questionsOf(question({ payload: {} }))).toEqual([]);
  });
});

describe("reviewOf", () => {
  it("reads the stats and changed paths", () => {
    expect(reviewOf(review())).toEqual({
      files: 3,
      additions: 48,
      deletions: 19,
      paths: ["a.css", "b.tsx", "c.tsx"],
      summary: "Raised contrast",
    });
    expect(reviewOf(review({ payload: { paths: ["a", 1] } })).paths).toEqual(["a"]);
  });
});

describe("planOf", () => {
  it("reads the plan's markdown", () => {
    expect(planOf(plan())).toBe("## Plan\n\n1. Add **zod**\n2. Validate the form");
    expect(planOf(plan({ payload: { plan: 3 } }))).toBe("");
  });
});

describe("contextOf", () => {
  it("reads the context window's use, or nothing", () => {
    expect(contextOf({ percent: 41.4, used: 82_000, limit: 200_000 })).toEqual({
      percent: 41.4,
      used: 82_000,
      limit: 200_000,
    });
    expect(contextOf(null)).toBeNull();
    expect(contextOf(undefined)).toBeNull();
    expect(contextOf({ percent: "41", used: 1, limit: 2 })).toBeNull();
    expect(contextOf({ percent: 41, used: 1 })).toBeNull();
  });
});

describe("queuedOf", () => {
  it("keeps well formed queued messages in order", () => {
    const attachment = { id: "a1", filename: "a.png", media_type: "image/png", size: 3 };
    const first = queuedMessage({ attachments: [attachment], sent: true });
    const second = queuedMessage({ id: "m2", text: "And docs" });

    expect(
      queuedOf([
        { ...first },
        "junk",
        { id: "x" },
        { ...second },
        { id: "m3", text: "Bare" },
      ] as never),
    ).toEqual([
      first,
      second,
      { id: "m3", text: "Bare", attachments: [], created_at: "", sent: false },
    ]);
    expect(queuedOf(undefined)).toEqual([]);
  });
});

describe("prOf", () => {
  it("reads a pull request status, or nothing when malformed", () => {
    const pr = prStatus();

    expect(prOf(pr as unknown as JsonValue)).toEqual(pr);
    expect(prOf(null)).toBeNull();
    expect(prOf({ number: 7, state: "open" })).toBeNull();
    expect(prOf({ number: "7", state: "open", checks: { items: [] } })).toBeNull();
    expect(prOf({ number: 7, checks: { items: [] } })).toBeNull();
  });
});

describe("mergeOf", () => {
  it("reads the pull request and how many checks passed", () => {
    expect(mergeOf(mergeApproval())).toEqual({
      number: 7,
      title: "Validate contact form",
      url: "https://github.com/me/todo-ui/pull/7",
      passed: 2,
    });
  });

  it("falls back on the approval's title", () => {
    expect(mergeOf(mergeApproval({ payload: {}, title: "Chat title" }))).toEqual({
      number: 0,
      title: "Chat title",
      url: "",
      passed: 0,
    });
  });
});

describe("stuckOf", () => {
  it("reads a stuck flag and rejects anything else", () => {
    const since = "2026-10-06T10:00:00Z";
    expect(stuckOf({ reason: "repeating", since, details: "Called Bash 5 times" })).toEqual({
      reason: "repeating",
      since,
      details: "Called Bash 5 times",
    });
    expect(stuckOf({ reason: "silent", since })).toEqual({ reason: "silent", since, details: "" });
    expect(stuckOf({ reason: "bored", since })).toBeNull();
    expect(stuckOf({ since })).toBeNull();
    expect(stuckOf({ reason: "silent" })).toBeNull();
  });
});

describe("local model failures", () => {
  const down = { app: "LM Studio", address: "http://127.0.0.1:1234", start: "lmstudio" };

  it("reads a refused send's server, and nothing from other refusals", () => {
    const refused = new ApiError(409, "LM Studio is not running", "local_server_down", {
      code: "local_server_down",
      ...down,
    });
    expect(serverDownOf(refused)).toEqual({ code: "local_server_down", ...down });
    expect(serverDownOf(new ApiError(409, "Busy", "turn_running", down))).toBeNull();
    expect(serverDownOf(new ApiError(502, "x", "local_server_down", down))).toBeNull();
    expect(serverDownOf(new Error("offline"))).toBeNull();
  });

  it("reads a failed turn's state, offering only an app Nest can start", () => {
    const state = { state: "failed", error: "gone", code: "local_server_down" };
    expect(localFailureOf({ ...state, ...down, start: "vllm" })).toEqual({
      code: "local_server_down",
      app: "LM Studio",
      address: "http://127.0.0.1:1234",
      start: null,
    });
    expect(
      localFailureOf({
        state: "failed",
        code: "local_model_not_loaded",
        detail: "LM Studio could not load gpt-oss-20b",
        app: "LM Studio",
        address: "http://127.0.0.1:1234",
        model: "gpt-oss-20b",
      }),
    ).toEqual({
      code: "local_model_not_loaded",
      detail: "LM Studio could not load gpt-oss-20b",
      app: "LM Studio",
      address: "http://127.0.0.1:1234",
      model: "gpt-oss-20b",
    });
    expect(localFailureOf({ state: "failed", error: "boom" })).toBeNull();
  });
});
