// Ported from NestKitTests' PublishTests: what the approve sheet offers per chat and what
// each choice sends, and each git step's progress.
import { describe, expect, it } from "vitest";
import { ApiError } from "../../api/client.ts";
import type { Session } from "../../api/types.ts";
import { diff, event, prStatus, review, session } from "../../test/fixtures.ts";
import {
  applyGitEvent,
  approveBody,
  canOpenPR,
  doneText,
  failProgress,
  formNote,
  formTitle,
  publishFailure,
  publishForm,
  remoteSummary,
  remoteTarget,
  startProgress,
  steps,
} from "./publish.ts";

const seen = diff();
const SENT = { expected_fingerprint: "f1ngerprint", expected_head: seen.head.commit };
const ap = review({ title: "Dark mode contrast" });
const worktree = session();
const inPlace = session({ mode: "in_place" });
const withPr = (state: "open" | "merged" | "closed"): Session =>
  session({ pr_url: "https://github.com/me/cv/pull/8", pr: prStatus({ number: 8, state }) });

describe("the approve sheet's choices", () => {
  it("opens a pull request from a worktree chat, with optional trimmed title and body", () => {
    const form = publishForm(ap, worktree);
    expect(canOpenPR(form)).toBe(true);
    expect(steps(form)).toEqual(["commit", "push", "pr"]);
    expect(formTitle(form)).toBe("Approve and open PR");
    expect(formNote(form)).toBeNull();
    expect(approveBody(form, seen)).toEqual({
      commit_message: "Dark mode contrast",
      push: true,
      open_pr: true,
      ...SENT,
    });
    const filled = {
      ...form,
      commitMessage: "  Raise contrast \n",
      prTitle: " Better ",
      prBody: " ",
    };
    expect(approveBody(filled, seen)).toEqual({
      commit_message: "Raise contrast",
      push: true,
      open_pr: true,
      pr_title: "Better",
      ...SENT,
    });
    expect(doneText(form, "Fix")).toBe("Opened a pull request for Fix");
  });

  it("commits without pushing when the switch is off", () => {
    const form = {
      ...publishForm(ap, worktree),
      openPR: false,
      prTitle: "Ignored",
      confirmRemoteUrl: "git@github.com:me/cv.git",
    };
    expect(steps(form)).toEqual(["commit"]);
    expect(formTitle(form)).toBe("Approve and commit");
    expect(approveBody(form, seen)).toEqual({
      commit_message: "Dark mode contrast",
      push: false,
      open_pr: false,
      ...SENT,
    });
    expect(doneText(form, "Fix")).toBe("Committed Fix without pushing");
  });

  it("commits only the reviewed files of an in-place chat, with no switch", () => {
    const form = publishForm(ap, inPlace);
    expect(canOpenPR(form)).toBe(false);
    expect(steps(form)).toEqual(["commit"]);
    expect(approveBody(form, seen)).toEqual({
      commit_message: "Dark mode contrast",
      files: ["a.css", "b.tsx", "c.tsx"],
      push: false,
      open_pr: false,
      ...SENT,
    });
    expect(formNote(form)).toBe(
      "This chat works in the project folder, so its files are committed on the current branch, without pushing or a pull request.",
    );
    expect(doneText(form, "Fix")).toBe("Committed Fix without pushing");
  });

  it("pushes to an open pull request, or only commits from Approve and commit", () => {
    const form = { ...publishForm(ap, withPr("open")), confirmRemoteUrl: "git@h:r.git" };
    expect(canOpenPR(form)).toBe(false);
    expect(steps(form)).toEqual(["commit", "push"]);
    expect(formTitle(form)).toBe("Approve and push to #8");
    expect(approveBody(form, seen)).toEqual({
      commit_message: "Dark mode contrast",
      push: true,
      open_pr: false,
      confirm_remote_url: "git@h:r.git",
      ...SENT,
    });
    expect(doneText(form, "Fix")).toBe("Pushed Fix to #8");

    const commit = publishForm(ap, withPr("open"), true);
    expect(steps(commit)).toEqual(["commit"]);
    expect(formTitle(commit)).toBe("Approve and commit");
    expect(approveBody(commit, seen)).toMatchObject({ push: false, open_pr: false });
    expect(formNote(commit)).toMatch(/already open/);
  });

  it("only commits for a merged or closed pull request", () => {
    for (const state of ["merged", "closed"] as const) {
      const form = publishForm(ap, withPr(state));
      expect(canOpenPR(form)).toBe(false);
      expect(steps(form)).toEqual(["commit"]);
      expect(approveBody(form, seen)).toMatchObject({ push: false, open_pr: false });
      expect(formNote(form)).toBe(
        "This chat's pull request is no longer open. Approve commits to its branch without pushing.",
      );
    }
  });

  it("says where origin pushes after a refusal", () => {
    expect(remoteSummary({ urls: ["git@new:r.git"], confirmed: "git@old:r.git" })).toBe(
      "origin now pushes to",
    );
    expect(remoteTarget({ urls: ["a"], confirmed: null })).toBe("a");
    expect(remoteTarget({ urls: [], confirmed: null })).toBeNull();
    expect(remoteTarget({ urls: ["a", "b"], confirmed: null })).toBeNull();
  });
});

describe("the approve steps", () => {
  it("follow the daemon's git events in order", () => {
    let progress = startProgress(["commit", "push", "pr"]);
    expect(progress.steps.map((s) => s.state)).toEqual(["running", "pending", "pending"]);
    progress = applyGitEvent(progress, event({ type: "git.pushed" }));
    expect(progress.steps.map((s) => s.state)).toEqual(["done", "done", "running"]);
    progress = applyGitEvent(
      progress,
      event({ type: "git.failed", payload: { step: "pr", stderr: "no gh" } }),
    );
    expect(progress.steps.map((s) => [s.state, s.output])).toEqual([
      ["done", ""],
      ["done", ""],
      ["failed", "no gh"],
    ]);
  });

  it("show a git failure on its step, its output or else its message", () => {
    const failure = publishFailure(
      new ApiError(502, "git push failed", null, { step: "push", stderr: " \n" }),
    );
    const progress = failProgress(startProgress(["commit", "push"]), failure);
    expect(progress.running).toBe(false);
    expect(progress.steps.map((s) => [s.state, s.output])).toEqual([
      ["done", ""],
      ["failed", "git push failed"],
    ]);
  });

  it("stay pending after a refusal, with the reason and the push address to confirm", () => {
    const failure = publishFailure(
      new ApiError(409, "origin changed", "remote_changed", {
        remote_urls: ["git@new:r.git"],
        confirmed_url: "git@old:r.git",
      }),
    );
    const progress = failProgress(startProgress(["commit", "push"]), failure);
    expect(progress.steps.map((s) => s.state)).toEqual(["pending", "pending"]);
    expect(progress.failure?.remote).toEqual({
      urls: ["git@new:r.git"],
      confirmed: "git@old:r.git",
    });
    const moved = publishFailure(new ApiError(409, "moved", "head_changed"));
    expect(moved.hint).toBe("The branch moved since you looked. Check the changes again.");
  });

  it("mark the running step when the call fails without one", () => {
    const failure = publishFailure(new TypeError("Failed to fetch"));
    const progress = failProgress(startProgress(["commit", "push"]), failure);
    expect(progress.steps.map((s) => [s.state, s.output])).toEqual([
      ["failed", "Failed to fetch"],
      ["pending", ""],
    ]);
  });
});
