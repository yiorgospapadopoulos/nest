import { describe, expect, it } from "vitest";
import { prStatus, session } from "../../test/fixtures.ts";
import { initialState } from "../../store/state.ts";
import {
  guideView,
  mergesWhenReady,
  mergeWhenReadyLine,
  restackAction,
  restackTitle,
  stackParent,
} from "./prWork.ts";

describe("merge when checks pass", () => {
  it("is on when Nest waits to merge or when GitHub's auto-merge is on", () => {
    const off = session({ pr: prStatus() });
    const nest = session({
      pr: prStatus(),
      merge_when_ready: { method: "squash", delete_branch: false },
    });
    const github = session({
      pr: prStatus({ auto_merge: { method: "squash", enabled_at: null } }),
    });

    expect(mergesWhenReady(off)).toBe(false);
    expect(mergeWhenReadyLine(off)).toBeNull();
    expect(mergesWhenReady(nest)).toBe(true);
    expect(mergeWhenReadyLine(nest)).toBe("Nest merges it when checks pass, while Nest is running");
    expect(mergesWhenReady(github)).toBe(true);
    expect(mergeWhenReadyLine(github)).toBe("GitHub merges it when checks pass");
  });
});

describe("moving a stacked branch", () => {
  it("offers only what is left: push, rebase and push, or rebase without a pull request", () => {
    expect(restackAction(true, true).label).toBe("Push");
    expect(restackAction(false, true).label).toBe("Rebase and push");
    expect(restackAction(false, false).label).toBe("Rebase");
  });

  it("titles the card by whether the rebase happened", () => {
    const view = { branch: "wip", base: "main", error: null, url: null };
    expect(restackTitle({ ...view, rebased: false, number: 12 })).toBe("Move wip onto main");
    expect(restackTitle({ ...view, rebased: true, number: 12 })).toBe("#12 wip moved onto main");
  });

  it("names the chat under it by its pull request, else by its title", () => {
    const parent = session({ id: "p1", title: "Base work", pr: null });
    const child = session({
      id: "c1",
      stack: { parent: "p1", parent_branch: "agent/base", restack: null },
    });
    const state = { ...initialState, sessions: { p1: parent, c1: child } };

    expect(stackParent(state, child)).toEqual({ id: "p1", text: "On top of Base work" });
    const withPr = { ...state, sessions: { ...state.sessions, p1: { ...parent, pr: prStatus() } } };
    expect(stackParent(withPr, child)).toEqual({ id: "p1", text: "On top of #7" });
    expect(stackParent(state, session({ stack: null }))).toBeNull();
  });
});

describe("the review guide", () => {
  it("offers writing again once the pull request has a newer head", () => {
    const guide = {
      state: "ready" as const,
      head_sha: "abc123",
      artifact_id: "a1",
      error: null,
      comment_url: null,
      written_at: null,
    };
    const chat = session({ pr_guide: guide });

    expect(guideView(chat, prStatus({ head_sha: "abc123" }))).toMatchObject({ stale: false });
    expect(guideView(chat, prStatus({ head_sha: "def456" }))).toMatchObject({ stale: true });
  });
});
