/// <reference types="node" />
import { readFileSync } from "node:fs";
import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Approval, ApprovalKind, Session } from "../api/types.ts";
import { KINDS } from "../screens/settings/notifyKinds.ts";
import { fakeApi } from "../test/fakeApi.ts";
import { approval, check, prStatus, session } from "../test/fixtures.ts";
import { renderApp } from "../test/render.tsx";
import {
  chatGroup,
  chatStatus,
  ciFailure,
  GROUP_LABELS,
  GROUP_ORDER,
  needsCount,
  type ChatGroup,
  type Tone,
} from "./selectors.ts";
import { initialState, type State } from "./state.ts";

// The table both clients follow (IMP-10); the Mac's own test checks it too.
interface StatusCase {
  state: Session["state"];
  pending: ApprovalKind[];
  stuck?: boolean;
  pinned?: boolean;
  label: string;
  tone: string;
  group: string;
}

interface Rules {
  status: { cases: StatusCase[] };
  groups: { id: string; label: string }[];
  badge: {
    counts: string[];
    checks_failed: {
      pr_state: string;
      checks_state: string;
      not_in_states: Session["state"][];
      not_with_pending: ApprovalKind[];
      not_archived: boolean;
    };
  };
  needs_you: { order: string[]; approvals: string; checks_failed: string; stuck: string };
  notification_kinds: { kind: string; label: string }[];
}

const rules = JSON.parse(readFileSync("../design/ui-rules.json", "utf8")) as Rules;

// The PWA's short names for the shared tones and groups.
const TONES: Record<Tone, string> = {
  run: "running",
  wait: "waiting",
  rev: "review",
  fail: "failed",
  int: "interrupted",
  done: "done",
  idle: "idle",
};
const GROUPS: Record<ChatGroup, string> = {
  pinned: "pinned",
  need: "needs_you",
  run: "running",
  idle: "idle",
  done: "done",
};

const STUCK = { reason: "silent" as const, since: "2026-10-06T09:00:00Z", details: "No output." };

function pendingOf(kinds: ApprovalKind[], sessionId = "s1"): Approval[] {
  return kinds.map((kind, index) =>
    approval({ id: `${sessionId}-${String(index)}`, session_id: sessionId, kind }),
  );
}

describe("the shared UI rules", () => {
  it.each(rules.status.cases)("give $state with $pending: $label", (rule) => {
    const chat = session({
      state: rule.state,
      stuck: rule.stuck === true ? STUCK : null,
      pinned: rule.pinned === true,
    });
    const status = chatStatus(chat, pendingOf(rule.pending));

    expect({
      label: status.label,
      tone: TONES[status.tone],
      group: GROUPS[chatGroup(chat, status)],
    }).toEqual({
      label: rule.label,
      tone: rule.tone,
      group: rule.group,
    });
  });

  it("list the chat groups in order with their names", () => {
    expect(GROUP_ORDER.map((group) => ({ id: GROUPS[group], label: GROUP_LABELS[group] }))).toEqual(
      rules.groups,
    );
  });

  it("count pending approvals, failed checks and stuck chats in the badge", () => {
    expect(rules.badge.counts).toEqual(["approvals", "checks_failed", "stuck"]);
    const failing = prStatus({ checks: [check("unit", "failure")] });
    const sessions = [
      session({ id: "a" }),
      session({ id: "b", pr: failing }),
      session({ id: "c", state: "running", stuck: STUCK }),
      session({ id: "d", stuck: STUCK, archived_at: "2026-10-06T11:00:00Z" }),
    ];
    const state: State = {
      ...initialState,
      sessions: Object.fromEntries(sessions.map((s) => [s.id, s])),
      approvals: Object.fromEntries(pendingOf(["permission", "review"], "a").map((a) => [a.id, a])),
    };

    expect(needsCount(state)).toBe(2 + 1 + 1);
  });

  it("count a failed check only while the chat waits for the user", () => {
    const rule = rules.badge.checks_failed;
    const failing = prStatus({ checks: [check("unit", "failure")] });
    expect([rule.pr_state, rule.checks_state, rule.not_archived]).toEqual([
      "open",
      "failure",
      true,
    ]);

    expect(ciFailure(session({ pr: failing }), [])).not.toBeNull();
    // Every state the status table knows: those listed hide the card, all others count.
    const states = [...new Set(rules.status.cases.map((c) => c.state))];
    expect(states).toHaveLength(7);
    for (const state of states) {
      const found = ciFailure(session({ pr: failing, state }), []);
      if (rule.not_in_states.includes(state)) expect(found, state).toBeNull();
      else expect(found, state).not.toBeNull();
    }
    expect(ciFailure(session({ pr: failing }), pendingOf(rule.not_with_pending))).toBeNull();
    expect(ciFailure(session({ pr: failing, archived_at: "x" }), [])).toBeNull();
    expect(ciFailure(session({ pr: { ...failing, state: "merged" } }), [])).toBeNull();
    expect(ciFailure(session({ pr: prStatus() }), [])).toBeNull();
  });

  it("order the Needs you cards", async () => {
    expect([
      rules.needs_you.approvals,
      rules.needs_you.checks_failed,
      rules.needs_you.stuck,
    ]).toEqual(["oldest_first", "oldest_check_change_first", "longest_stuck_first"]);
    const api = fakeApi();
    const at = (minute: number) => `2026-10-06T09:${String(minute).padStart(2, "0")}:00Z`;
    const failing = (id: string, minute: number) =>
      session({
        id,
        title: id,
        pr: prStatus({ checks: [check("unit", "failure")], changed_at: at(minute) }),
      });
    const stuck = (id: string, minute: number) =>
      session({ id, title: id, state: "running", stuck: { ...STUCK, since: at(minute) } });
    api.sessions.mockImplementation((archived) =>
      Promise.resolve(
        archived
          ? []
          : [
              session(),
              stuck("stuck-late", 30),
              failing("failed-late", 20),
              stuck("stuck-early", 5),
              failing("failed-early", 10),
            ],
      ),
    );
    api.approvals.mockResolvedValue([
      approval({ id: "late", title: "late", created_at: at(40) }),
      approval({ id: "early", kind: "question", title: "early", created_at: at(1) }),
    ]);
    await renderApp({ api });

    const sections: Record<string, string> = {
      Permission: "approvals",
      Question: "approvals",
      "Checks failed": "checks_failed",
      Stuck: "stuck",
    };
    const cards = screen
      .getAllByRole("article")
      .map((card) => card.getAttribute("aria-label") ?? "");
    expect([...new Set(cards.map((label) => sections[label.split(":")[0] ?? ""]))]).toEqual(
      rules.needs_you.order,
    );
    expect(cards).toEqual([
      "Question: early",
      "Permission: late",
      "Checks failed: failed-early",
      "Checks failed: failed-late",
      "Stuck: stuck-early",
      "Stuck: stuck-late",
    ]);
  });

  it("name the notification kinds in the settings' order", () => {
    expect(KINDS).toEqual(rules.notification_kinds);
  });
});
