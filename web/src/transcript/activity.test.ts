import { describe, expect, it } from "vitest";
import { elapsed, summarizeTools, thoughtLabel, toolKind, turnLabel } from "./activity.ts";

const tool = (name: string, result: string | null = "done", failed = false, id = name) => ({
  id,
  name,
  result,
  failed,
});
const NONE = new Set<string>();

describe("elapsed", () => {
  it("reads like a stopwatch: seconds, then minutes, then hours", () => {
    expect(elapsed(0)).toBe("0s");
    expect(elapsed(999)).toBe("0s");
    expect(elapsed(12_400)).toBe("12s");
    expect(elapsed(60_000)).toBe("1m 0s");
    expect(elapsed(72_000)).toBe("1m 12s");
    expect(elapsed(3_599_999)).toBe("59m 59s");
    expect(elapsed(3_720_000)).toBe("1h 2m");
    expect(elapsed(-5)).toBe("0s");
  });
});

describe("labels", () => {
  it("says how long the agent thought, at least a second, or just that it did", () => {
    expect(thoughtLabel(8_000)).toBe("Thought for 8s");
    expect(thoughtLabel(120)).toBe("Thought for 1s");
    expect(thoughtLabel(null)).toBe("Thought");
  });

  it("says how long a turn worked or ran before it stopped", () => {
    expect(turnLabel(72_000, false)).toBe("Worked for 1m 12s");
    expect(turnLabel(40_000, true)).toBe("Stopped after 40s");
    expect(turnLabel(10, false)).toBe("Worked for 1s");
  });
});

describe("toolKind", () => {
  it("sorts tools into the kinds a group counts", () => {
    expect(["Bash", "Read", "Edit", "Write", "MultiEdit", "NotebookEdit"].map(toolKind)).toEqual([
      "command",
      "read",
      "edit",
      "edit",
      "edit",
      "edit",
    ]);
    expect(
      ["Grep", "Glob", "WebFetch", "WebSearch", "Task", "Agent", "Skill"].map(toolKind),
    ).toEqual(["search", "search", "fetch", "fetch", "agent", "agent", "other"]);
  });
});

describe("summarizeTools", () => {
  it("counts finished tools by kind in the past tense, in the order they first ran", () => {
    const summary = summarizeTools(
      [
        tool("Bash"),
        tool("Read"),
        tool("Bash"),
        tool("Edit"),
        tool("Read"),
        tool("Bash"),
        tool("Write"),
      ],
      NONE,
    );
    expect(summary).toEqual({
      text: "Ran 3 commands, read 2 files, edited 2 files",
      running: false,
      failed: 0,
    });
  });

  it("uses the present tense while any tool runs", () => {
    expect(summarizeTools([tool("Bash", null), tool("Bash"), tool("Read")], NONE)).toEqual({
      text: "Running 2 commands, reading 1 file",
      running: true,
      failed: 0,
    });
    expect(summarizeTools([tool("Edit"), tool("Grep", null)], NONE).text).toBe(
      "Editing 1 file, searching 1 pattern",
    );
  });

  it("names searches, fetches and other tools", () => {
    expect(
      summarizeTools(
        [
          tool("Grep"),
          tool("Glob"),
          tool("WebFetch"),
          tool("Skill"),
          tool("mcp__notes__find"),
          tool("Skill"),
        ],
        NONE,
      ).text,
    ).toBe("Searched 2 patterns, fetched 1 page, used Skill 2 times, used mcp__notes__find");
    expect(summarizeTools([tool("WebSearch", null), tool("Skill")], NONE).text).toBe(
      "Fetching 1 page, using Skill",
    );
    expect(summarizeTools([tool("Skill", null), tool("Skill")], NONE).text).toBe(
      "Using Skill 2 times",
    );
  });

  it("counts agents and how many are done while they run", () => {
    const agents = [
      tool("Agent", null, false, "a1"),
      tool("Task", "done", false, "a2"),
      tool("Agent", "Started in the background", false, "a3"),
    ];
    // A background agent's call returns at once; it still runs until tracking says so.
    expect(summarizeTools(agents, new Set(["a3"])).text).toBe("Running 3 agents, 1 done");
    expect(summarizeTools(agents.slice(2), new Set(["a3"])).running).toBe(true);
    expect(summarizeTools([tool("Agent", null), tool("Agent", null)], NONE).text).toBe(
      "Running 2 agents",
    );
    expect(summarizeTools([tool("Agent"), tool("Task"), tool("Read")], NONE).text).toBe(
      "Ran 2 agents, read 1 file",
    );
  });

  it("counts failed tools", () => {
    expect(summarizeTools([tool("Bash", "failed", true), tool("Bash")], NONE)).toEqual({
      text: "Ran 2 commands",
      running: false,
      failed: 1,
    });
  });
});
