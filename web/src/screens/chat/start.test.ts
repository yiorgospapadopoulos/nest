import { describe, expect, it } from "vitest";
import type { Approval, Session } from "../../api/types.ts";
import { initialState, type State } from "../../store/state.ts";
import {
  approval,
  check,
  mergeApproval,
  plan,
  prStatus,
  question,
  repo,
  review,
  session,
} from "../../test/fixtures.ts";
import {
  age,
  needsYouLine,
  question as ask,
  QUESTION_COUNT,
  rotation,
  startLists,
} from "./start.ts";

function state(sessions: Session[], approvals: Approval[] = []): State {
  return {
    ...initialState,
    repos: [repo("cv-page"), repo("narrative")],
    sessions: Object.fromEntries(sessions.map((s) => [s.id, s])),
    approvals: Object.fromEntries(approvals.map((a) => [a.id, a])),
  };
}

const minutesAgo = (minutes: number) =>
  new Date(Date.parse("2026-10-06T10:00:00Z") - minutes * 60_000).toISOString();

describe("start screen question", () => {
  it("asks eight ways, naming the project as the Mac does", () => {
    const named = Array.from({ length: QUESTION_COUNT }, (_, i) => ask(i, "nest"));
    expect(named).toEqual([
      "What should we work on in nest?",
      "What's next for nest?",
      "Where should we start in nest?",
      "What are we building in nest today?",
      "What needs doing in nest?",
      "What should we fix or build in nest?",
      "What's on your mind for nest?",
      "What shall we tackle in nest?",
    ]);
    // An index past the end wraps around.
    expect(ask(9, "nest")).toBe("What's next for nest?");
  });

  it("asks the next question each time the screen appears, never the same twice in a row", () => {
    const turns = rotation();
    const asked = Array.from({ length: QUESTION_COUNT + 2 }, () => turns.next());
    expect(asked).toEqual([0, 1, 2, 3, 4, 5, 6, 7, 0, 1]);
    expect(asked.every((index, i) => i === 0 || index !== asked[i - 1])).toBe(true);
  });
});

describe("start screen ages", () => {
  const now = new Date("2026-10-06T10:00:00Z");

  it("shows the largest whole unit only", () => {
    expect(age(minutesAgo(0.5), now)).toBe("now");
    expect(age(minutesAgo(9), now)).toBe("9m");
    expect(age(minutesAgo(125), now)).toBe("2h");
    expect(age(minutesAgo(3 * 1440 + 5), now)).toBe("3d");
    // A clock a little ahead of the Mac's is "now", not a negative age.
    expect(age(minutesAgo(-3), now)).toBe("now");
  });
});

describe("needs you line", () => {
  it("names the kind and a short detail, as the Mac's right panel", () => {
    expect(needsYouLine(approval())).toBe("Permission · Bash npm install zod");
    expect(
      needsYouLine(approval({ payload: { tool: "Edit", input: { file_path: "/w/a.ts" } } })),
    ).toBe("Permission · Edit /w/a.ts");
    expect(needsYouLine(question())).toBe("Question · DAG or tree?");
    expect(needsYouLine(review())).toBe("Ready for review · +48 -19 in 3 files");
    expect(needsYouLine(review({ payload: { files: 1, additions: 2, deletions: 0 } }))).toBe(
      "Ready for review · +2 -0 in 1 file",
    );
    expect(needsYouLine(plan())).toBe("Plan · Plan");
    expect(needsYouLine(plan({ payload: { plan: "\n" } }))).toBe("Plan");
    expect(needsYouLine(mergeApproval())).toBe("Ready to merge · #7 Validate contact form");
    expect(needsYouLine(question({ payload: { questions: [] } }))).toBe("Question");
  });
});

describe("start screen lists", () => {
  it("lists this project's approvals, failed checks, then stuck chats", () => {
    const failing = session({
      id: "s2",
      title: "Add RSS",
      pr: prStatus({ checks: [check("test", "failure"), check("e2e", "failure")] }),
      pr_url: "https://github.com/me/cv-page/pull/7",
    });
    const stuck = session({
      id: "s3",
      title: "Bump Next",
      state: "running",
      stuck: { reason: "silent", since: minutesAgo(12), details: "No new output for 12 minutes" },
    });
    const other = session({ id: "s4", repo: "narrative" });
    const lists = startLists(
      state(
        [session(), failing, stuck, other],
        [
          approval(),
          review({ id: "q9" }),
          approval({ id: "q8", session_id: "s4", repo: "narrative" }),
        ],
      ),
      "cv-page",
    );

    expect(lists.waiting.map((w) => [w.chat, w.title, w.tone, w.line])).toEqual([
      ["s1", "Validate contact form", "wait", "Permission · Bash npm install zod"],
      ["s1", "Validate contact form", "rev", "Ready for review · +48 -19 in 3 files"],
      ["s2", "Add RSS", "fail", "Checks failed · test, e2e"],
      ["s3", "Bump Next", "wait", "Stuck · No new output for 12 minutes"],
    ]);
    expect(new Set(lists.waiting.map((w) => w.id)).size).toBe(4);
    // Each chat waiting on the user is listed there, not again under Recent.
    expect(lists.recent).toEqual([]);
  });

  it("lists the latest four chats not waiting and not archived under Recent", () => {
    const chats = [
      session({ id: "a", updated_at: minutesAgo(50) }),
      session({ id: "b", updated_at: minutesAgo(5) }),
      session({ id: "c", updated_at: minutesAgo(30) }),
      session({ id: "d", updated_at: minutesAgo(30) }),
      session({ id: "e", updated_at: minutesAgo(1), archived_at: minutesAgo(1) }),
      session({ id: "f", updated_at: minutesAgo(90) }),
      session({ id: "g", updated_at: minutesAgo(2) }),
    ];
    const lists = startLists(state(chats, [approval({ session_id: "g" })]), "cv-page");

    expect(lists.recent.map((r) => r.id)).toEqual(["b", "d", "c", "a"]);
  });

  it("names an approval by its own title while its chat is not loaded", () => {
    const lists = startLists(
      state([], [approval({ session_id: "gone", title: "Old chat" })]),
      "cv-page",
    );

    expect(lists.waiting.map((w) => w.title)).toEqual(["Old chat"]);
  });
});
