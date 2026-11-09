import { describe, expect, it } from "vitest";
import type { GitHubWatch } from "../api/types.ts";
import {
  githubDraftOf,
  githubText,
  parseList,
  triggerBody,
  triggerSummary,
  watchesOf,
  newTriggerDraft,
} from "./github.ts";

const watch = (fields: Partial<GitHubWatch>): GitHubWatch => ({
  events: ["ci_failed"],
  projects: [],
  labels: [],
  branches: [],
  authors: "members",
  ...fields,
});

describe("GitHub triggers", () => {
  it("edits a habit's first trigger and keeps the others a pixie made", () => {
    const before = [watch({ branches: ["main"] }), watch({ events: ["review"] })];
    const draft = { ...githubDraftOf(before), labels: " bug, ui,bug ", branches: "" };

    expect(watchesOf(draft, before)).toEqual([watch({ labels: ["bug", "ui"] }), before[1]]);
    // No events left removes only the first.
    expect(watchesOf({ ...draft, events: [] }, before)).toEqual([before[1]]);
  });

  it("starts a new trigger in Ask and shows any other mode on its row", () => {
    expect(newTriggerDraft().mode).toBe("default");
    expect(triggerSummary({ ...watch({}), permission_mode: "default" })).toBe("When CI fails");
    expect(triggerSummary({ ...watch({}), permission_mode: "bypassPermissions" })).toBe(
      "When CI fails · Bypass",
    );
  });

  it("says what a trigger waits for", () => {
    expect(githubText([watch({ events: ["ci_failed", "issue_opened"] })])).toBe(
      "On GitHub when an issue is opened or CI fails",
    );
    expect(githubText([])).toBeNull();
    expect(triggerSummary(watch({ branches: ["main"], labels: ["bug"], authors: "humans" }))).toBe(
      "When CI fails · on main · labelled bug · anyone but bots",
    );
  });

  it("sends a trigger with its lists split and its text trimmed", () => {
    const draft = {
      ...newTriggerDraft(),
      name: " CI ",
      prompt: " Fix it. ",
      events: ["ci_passed", "ci_failed"] as GitHubWatch["events"],
      branches: "main, release/*",
    };

    expect(triggerBody(draft)).toEqual({
      name: "CI",
      prompt: "Fix it.",
      enabled: true,
      events: ["ci_failed", "ci_passed"],
      labels: [],
      branches: ["main", "release/*"],
      authors: "members",
      permission_mode: "default",
    });
    expect(parseList(" , ")).toEqual([]);
  });
});
