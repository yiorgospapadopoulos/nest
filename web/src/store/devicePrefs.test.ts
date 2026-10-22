import { afterEach, describe, expect, it } from "vitest";
import {
  FEATURE_GROUPS_KEY,
  loadFeatureGroups,
  loadUsageBarHidden,
  saveFeatureGroups,
  saveUsageBarHidden,
  USAGE_BAR_HIDDEN_KEY,
} from "./devicePrefs.ts";

const broken = (): Storage => {
  throw new Error("blocked");
};

afterEach(() => {
  localStorage.clear();
});

describe("the usage bar's engines on this device (B102 item 29)", () => {
  it("remembers the engines unchecked, so new engines start shown", () => {
    expect(loadUsageBarHidden(() => localStorage)).toEqual([]);
    saveUsageBarHidden(() => localStorage, ["codex"]);
    expect(localStorage.getItem(USAGE_BAR_HIDDEN_KEY)).toBe('["codex"]');
    expect(loadUsageBarHidden(() => localStorage)).toEqual(["codex"]);
  });

  it("leaves out anything malformed", () => {
    localStorage.setItem(USAGE_BAR_HIDDEN_KEY, '["codex", 3, null]');
    expect(loadUsageBarHidden(() => localStorage)).toEqual(["codex"]);
    localStorage.setItem(USAGE_BAR_HIDDEN_KEY, '{"codex": true}');
    expect(loadUsageBarHidden(() => localStorage)).toEqual([]);
    localStorage.setItem(USAGE_BAR_HIDDEN_KEY, "not json");
    expect(loadUsageBarHidden(() => localStorage)).toEqual([]);
  });

  it("lasts until a reload when storage is unavailable", () => {
    expect(loadUsageBarHidden(broken)).toEqual([]);
    expect(() => {
      saveUsageBarHidden(broken, ["codex"]);
    }).not.toThrow();
  });
});

describe("the Features groups opened or closed on this device (B103)", () => {
  it("remembers each group's explicit choice", () => {
    expect(loadFeatureGroups(() => localStorage)).toEqual({});
    saveFeatureGroups(() => localStorage, { chats: true, git: false });
    expect(FEATURE_GROUPS_KEY).toBe("nest.features.groups");
    expect(loadFeatureGroups(() => localStorage)).toEqual({ chats: true, git: false });
  });

  it("leaves out anything malformed", () => {
    localStorage.setItem(FEATURE_GROUPS_KEY, '{"chats": true, "git": "yes", "pixies": false}');
    expect(loadFeatureGroups(() => localStorage)).toEqual({ chats: true, pixies: false });
    localStorage.setItem(FEATURE_GROUPS_KEY, '["chats"]');
    expect(loadFeatureGroups(() => localStorage)).toEqual({});
    localStorage.setItem(FEATURE_GROUPS_KEY, "null");
    expect(loadFeatureGroups(() => localStorage)).toEqual({});
    localStorage.setItem(FEATURE_GROUPS_KEY, "not json");
    expect(loadFeatureGroups(() => localStorage)).toEqual({});
  });

  it("lasts until a reload when storage is unavailable", () => {
    expect(loadFeatureGroups(broken)).toEqual({});
    expect(() => {
      saveFeatureGroups(broken, { chats: true });
    }).not.toThrow();
  });
});
