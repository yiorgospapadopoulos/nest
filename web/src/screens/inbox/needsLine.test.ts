// @vitest-environment node
import { describe, expect, it } from "vitest";
import {
  approval,
  callEntry,
  groupEntry,
  mergeApproval,
  pixie,
  question,
  review,
  reviewComments,
} from "../../test/fixtures.ts";
import { approvalLine, approvalPixie, checksFailedLine, lineText, stuckLine } from "./needsLine.ts";

// The grey line under each Needs you row, worded as NestKit's NeedsYouLine (B77).
describe("the Needs you line", () => {
  it("names a permission's tool and its argument", () => {
    expect(lineText(approvalLine(approval(), null))).toBe("Permission · Bash npm install zod");
    const edit = approval({
      payload: { tool: "Edit", input: { file_path: "/Users/me/todo-ui/src/form.ts" } },
    });
    expect(lineText(approvalLine(edit, "/Users/me/todo-ui"))).toBe("Permission · Edit src/form.ts");
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

  it("counts review comments on their pull request, saying when changes are requested", () => {
    expect(lineText(approvalLine(reviewComments(), null))).toBe(
      "Review comments · 4 on #7, changes requested",
    );
    const plain = reviewComments({ payload: { number: 9, comments: [{}] } });
    expect(lineText(approvalLine(plain, null))).toBe("Review comments · 1 on #9");
  });

  it("gives a plan's first line with text, without its heading marks", () => {
    const plan = (text: string) => approval({ kind: "plan", payload: { plan: text } });
    expect(lineText(approvalLine(plan("\n## Search page\n\nThen more"), null))).toBe(
      "Plan · Search page",
    );
    expect(lineText(approvalLine(plan("  \n#\n"), null))).toBe("Plan");
  });

  it("names the pixie whose call raised an item, its own call before its team slot's", () => {
    const pixies = {
      p1: pixie(),
      p2: pixie({ id: "p2", name: "Reviewer" }),
    };
    // A team's calls: the leader's slot a1, the member's own call a2.
    const groups = [
      groupEntry({
        kind: "team",
        pixie_id: null,
        team_id: "t1",
        calls: [callEntry(), callEntry({ id: "c2", pixie_id: "p2", tool_use_id: "a2" })],
      }),
    ];
    const raised = (payload: object) => approval({ payload: { tool: "Bash", ...payload } });

    expect(approvalPixie(raised({ call: "a1", agent: "a2" }), groups, pixies)?.name).toBe(
      "Reviewer",
    );
    expect(approvalPixie(raised({ call: "a1", agent: "inner" }), groups, pixies)?.name).toBe(
      "Tester",
    );
    expect(approvalPixie(raised({ call: "zz", agent: "zz" }), groups, pixies)).toBeNull();
    expect(approvalPixie(raised({ call: "a1", agent: "a2" }), undefined, pixies)).toBeNull();
    expect(approvalPixie(raised({}), groups, pixies)).toBeNull();
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
