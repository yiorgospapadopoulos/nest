import { afterEach, describe, expect, it } from "vitest";
import {
  loadMachine,
  loadUsageBarHidden,
  MACHINE_KEY,
  saveMachine,
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

describe("the daemon's machine name (B105)", () => {
  it("keeps the last name learned", () => {
    expect(loadMachine(() => localStorage)).toBeNull();
    saveMachine(() => localStorage, "Mac mini");
    expect(localStorage.getItem(MACHINE_KEY)).toBe("Mac mini");
    expect(loadMachine(() => localStorage)).toBe("Mac mini");
  });

  it("knows no name when storage is unavailable", () => {
    expect(loadMachine(broken)).toBeNull();
    expect(() => {
      saveMachine(broken, "Mac mini");
    }).not.toThrow();
  });
});
