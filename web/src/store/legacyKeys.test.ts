import { describe, expect, it } from "vitest";
import { STORAGE_KEY } from "../appearance/choices.ts";
import { memoryStorage } from "../test/render.tsx";
import { DRAFTS_KEY, FOLDED_TEAMS_KEY, SHOW_AUTOMATED_KEY } from "./devicePrefs.ts";
import { deviceStorage, LEGACY_KEYS, migrateLegacyKeys } from "./legacyKeys.ts";

// B43: what this device saved before the rename to Nest keeps working.
describe("the keys saved before the rename", () => {
  it("are every device choice under its old harness name", () => {
    expect(LEGACY_KEYS).toEqual([
      ["harness.appearance", STORAGE_KEY],
      ["harness.showAutomatedChats", SHOW_AUTOMATED_KEY],
      ["harness.foldedTeams", FOLDED_TEAMS_KEY],
      ["harness.drafts", DRAFTS_KEY],
    ]);
    expect([STORAGE_KEY, SHOW_AUTOMATED_KEY, FOLDED_TEAMS_KEY, DRAFTS_KEY]).toEqual([
      "nest.appearance",
      "nest.showAutomatedChats",
      "nest.foldedTeams",
      "nest.drafts",
    ]);
  });

  it("are copied to the new names, then removed", () => {
    const storage = memoryStorage();
    storage.setItem("harness.appearance", '{"theme":"dark"}');
    storage.setItem("harness.drafts", '{"s1":{"text":"hi","files":[]}}');
    storage.setItem("other", "kept");

    migrateLegacyKeys(storage);

    expect(storage.getItem(STORAGE_KEY)).toBe('{"theme":"dark"}');
    expect(storage.getItem(DRAFTS_KEY)).toBe('{"s1":{"text":"hi","files":[]}}');
    expect(storage.getItem("harness.appearance")).toBeNull();
    expect(storage.getItem("harness.drafts")).toBeNull();
    expect(storage.getItem(SHOW_AUTOMATED_KEY)).toBeNull();
    expect(storage.getItem("other")).toBe("kept");
  });

  it("never replace a choice already saved under the new name", () => {
    const storage = memoryStorage();
    storage.setItem("harness.foldedTeams", '["old"]');
    storage.setItem(FOLDED_TEAMS_KEY, '["new"]');

    migrateLegacyKeys(storage);

    expect(storage.getItem(FOLDED_TEAMS_KEY)).toBe('["new"]');
    expect(storage.getItem("harness.foldedTeams")).toBeNull();
  });

  it("stay where they are when the new one cannot be saved", () => {
    const storage = memoryStorage();
    storage.setItem("harness.showAutomatedChats", "true");
    storage.setItem = () => {
      throw new Error("QuotaExceededError");
    };

    migrateLegacyKeys(storage);

    expect(storage.getItem("harness.showAutomatedChats")).toBe("true");
    expect(storage.getItem(SHOW_AUTOMATED_KEY)).toBeNull();
  });

  it("move the first time this device's storage is used", () => {
    const storage = memoryStorage();
    storage.setItem("harness.appearance", '{"accent":"teal"}');
    Object.defineProperty(window, "localStorage", { configurable: true, value: storage });

    expect(deviceStorage()).toBe(storage);
    expect(storage.getItem(STORAGE_KEY)).toBe('{"accent":"teal"}');

    // Later uses do not look again.
    storage.setItem("harness.appearance", '{"accent":"rose"}');
    expect(deviceStorage()).toBe(storage);
    expect(storage.getItem(STORAGE_KEY)).toBe('{"accent":"teal"}');
  });
});
