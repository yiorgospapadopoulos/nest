import { describe, expect, it } from "vitest";
import type { WorktreeConfig } from "../../../api/types.ts";
import {
  addLink,
  addSetup,
  iconPatch,
  removalConsequence,
  removeLink,
  removeSetup,
  setupTimeoutChoices,
  setupTimeoutLabel,
  worktreePatch,
} from "./worktree.ts";

const config = (change: Partial<WorktreeConfig> = {}): WorktreeConfig => ({
  default: null,
  link: [],
  setup: [],
  setup_timeout_seconds: 900,
  ...change,
});

// Ported from NestKit's ProjectSettingsTests and SettingsTests.
describe("worktree settings", () => {
  it("keeps links inside the project", () => {
    let link: string[] = [];
    for (const text of ["  .env  ", "config/local.json", "node_modules/"]) {
      const next = addLink(link, text);
      expect(next).not.toBeNull();
      link = next ?? link;
    }
    for (const text of ["", "   ", ".env", "/etc/hosts", "../secrets", "a/../../b", ".", "./"]) {
      expect(addLink(link, text)).toBeNull();
    }
    expect(link).toEqual([".env", "config/local.json", "node_modules/"]);
  });

  it("adds trimmed setup commands and refuses blank ones", () => {
    expect(addSetup([], " npm ci \n")).toEqual(["npm ci"]);
    expect(addSetup(["npm ci"], "  ")).toBeNull();
  });

  it("removes by value, skipping an entry already gone", () => {
    expect(removeLink(["a", "b"], "b")).toEqual(["a"]);
    expect(removeLink(["a"], "zz")).toEqual(["a"]);
    const setup = ["npm ci", "make", "npm ci"];
    expect(removeSetup(setup, "npm ci", 2)).toEqual(["npm ci", "make"]);
    // The list changed since it was shown: the command at that place is another one.
    expect(removeSetup(["npm ci", "make"], "npm ci", 1)).toEqual(["npm ci", "make"]);
    expect(removeSetup(["npm ci", "make"], "npm ci", 9)).toEqual(["npm ci", "make"]);
  });

  it("offers the setup time limits with a value set elsewhere kept", () => {
    expect(setupTimeoutChoices(900)).toEqual([300, 900, 1800]);
    expect(setupTimeoutChoices(60)).toEqual([60, 300, 900, 1800]);
    expect(setupTimeoutLabel(900)).toBe("15 minutes");
    expect(setupTimeoutLabel(60)).toBe("1 minute");
    expect(setupTimeoutLabel(90)).toBe("90 seconds");
  });

  it("says what removing the project takes with it", () => {
    expect(removalConsequence(0)).toBe("Nest forgets this project. Its folder stays as it is.");
    expect(removalConsequence(1)).toMatch(
      /Its chat is deleted for good, with its worktree and history; its branch stays\.$/,
    );
    expect(removalConsequence(3)).toMatch(
      /Its 3 chats are deleted for good, with their worktrees and history; their branches stay\.$/,
    );
  });

  it("sends only what changed", () => {
    expect(worktreePatch(config(), config({ default: true }))).toEqual({ default: true });
    expect(worktreePatch(config({ default: true }), config())).toEqual({ default: null });
    expect(worktreePatch(config({ setup: ["a"] }), config())).toEqual({ setup: [] });
    expect(worktreePatch(config({ link: ["x"] }), config({ link: ["x"] }))).toEqual({});
    expect(iconPatch({ icon: null, icon_color: null }, { icon: "moth", icon_color: null })).toEqual(
      { icon: "moth" },
    );
    expect(
      iconPatch({ icon: "moth", icon_color: "#FF8800" }, { icon: null, icon_color: null }),
    ).toEqual({ icon: null, icon_color: null });
  });
});
