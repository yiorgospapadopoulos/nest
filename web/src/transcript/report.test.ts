import { describe, expect, it } from "vitest";
import { HAND_BACK } from "../test/fixtures.ts";
import { agentReport } from "./report.ts";

describe("agentReport", () => {
  it("keeps only the report of a subagent hand-back", () => {
    expect(agentReport(HAND_BACK)).toBe(
      "I'm New pixie 2 (@new-pixie-2-2), running on Claude Opus 5.5 (`claude-opus-5-5`).",
    );
  });

  it("drops the agent id and usage lines and the indentation of any result", () => {
    expect(
      agentReport("  Line one\n    nested\n\tTabbed\n line\nagentId: a1 (use SendMessage)\nmore"),
    ).toBe("Line one\n  nested\n\tTabbed\n line");
    expect(agentReport("Done.\n<usage>tool_uses: 0\nduration_ms: 9</usage>\n")).toBe("Done.");
    expect(agentReport("  plain answer  ")).toBe("plain answer");
  });

  it("falls back to the text as it came when nothing is left", () => {
    const empty = "[Subagent hand-back] Frame. The report follows:\nagentId: a1\n<usage>x</usage>";
    expect(agentReport(empty)).toBe(empty);
    expect(agentReport("[Subagent hand-back] no report marker")).toBe(
      "[Subagent hand-back] no report marker",
    );
    expect(agentReport("")).toBe("");
  });
});
