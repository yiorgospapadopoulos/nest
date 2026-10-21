import { describe, expect, it } from "vitest";
import { approval, mergeApproval, question, review } from "../../test/fixtures.ts";
import { approvalLine, checksFailedLine, lineText, stuckLine } from "./needsLine.ts";

// The grey line under each Needs you row, worded as NestKit's NeedsYouLine (B77).
describe("the Needs you line", () => {
  it("names a permission's tool and its argument", () => {
    expect(lineText(approvalLine(approval(), null))).toBe("Permission · Bash npm install zod");
    const edit = approval({
      payload: { tool: "Edit", input: { file_path: "/Users/me/cv-page/src/form.ts" } },
    });
    expect(lineText(approvalLine(edit, "/Users/me/cv-page"))).toBe("Permission · Edit src/form.ts");
    expect(lineText(approvalLine(approval({ payload: {} }), null))).toBe("Permission · Tool");
  });

  it("gives a question's first question, a review's changes and a merge's pull request", () => {
    expect(approvalLine(question(), null)).toEqual({
      kind: "Question",
      detail: "DAG or tree?",
    });
    expect(lineText(approvalLine(question({ payload: { questions: [] } }), null))).toBe("Question");
    expect(lineText(approvalLine(review(), null))).toBe("Ready for review · +48 -19 in 3 files");
    expect(
      lineText(approvalLine(review({ payload: { files: 1, additions: 1, deletions: 0 } }), null)),
    ).toBe("Ready for review · +1 -0 in 1 file");
    expect(lineText(approvalLine(mergeApproval(), null))).toBe(
      "Ready to merge · #7 Validate contact form",
    );
  });

  it("gives a plan's first line with text, without its heading marks", () => {
    const plan = (text: string) => approval({ kind: "plan", payload: { plan: text } });
    expect(lineText(approvalLine(plan("\n## Search page\n\nThen more"), null))).toBe(
      "Plan · Search page",
    );
    expect(lineText(approvalLine(plan("  \n#\n"), null))).toBe("Plan");
  });

  it("names failing checks, and why a chat looks stuck", () => {
    expect(lineText(checksFailedLine(["unit", "e2e"]))).toBe("Checks failed · unit, e2e");
    expect(lineText(checksFailedLine([]))).toBe("Checks failed");

    const flag = { since: "x", details: "No new output." };
    expect(lineText(stuckLine({ ...flag, reason: "waiting" }))).toBe("Stuck · Waiting too long");
    expect(lineText(stuckLine({ ...flag, reason: "silent" }))).toBe("Stuck · No new output");
    expect(lineText(stuckLine({ ...flag, reason: "repeating" }))).toBe("Stuck · Repeating a call");
    expect(lineText(stuckLine({ ...flag, reason: "long_turn" }))).toBe("Stuck · Very long turn");
  });
});
